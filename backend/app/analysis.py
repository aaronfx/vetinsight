"""Persisted experimental image analysis, isolated from human annotations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict

MODELS = Path(__file__).resolve().parents[1] / 'models'
LIMITATION = ('Experimental canine lymphosarcoma histology detector. Test AP50 0.094443. '
              'At score 0.5 it missed all 138 test mitoses. Patient independence is unverified. '
              'Scores are uncalibrated. Image scale, stain and specimen differences can reduce performance.')
CYTOLOGY_UNAVAILABLE = ('No cytology model is installed on this server. Image permissions and patient grouping '
                        'remain unresolved for veterinary cytology data.')
MAX_CYTOLOGY_PIXELS = 16_000_000
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='image-analysis')
gate = threading.Lock()
loaded = {}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS analysis_runs (
        id TEXT PRIMARY KEY, upload_id INTEGER NOT NULL REFERENCES uploads(id),
        actor_id INTEGER NOT NULL REFERENCES users(id), task TEXT NOT NULL,
        status TEXT NOT NULL, result TEXT NOT NULL, error TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );''')
    db.execute("UPDATE analysis_runs SET status='failed', error='Analysis interrupted by server restart. Start a new run.' WHERE status IN ('queued','running')")


def available(task='histology'):
    return (MODELS / f'{task}.pt').is_file() and (MODELS / f'{task}.json').is_file()


def limitation(task):
    if task == 'cytology':
        if not available('cytology'):
            return CYTOLOGY_UNAVAILABLE
        return json.loads((MODELS / 'cytology.json').read_text())['limitation']
    return LIMITATION


def load_model(task):
    """Load a packaged TorchScript detector after verifying its recorded SHA-256."""
    import torch
    import torchvision  # Registers the detection operators used by the packaged model.
    metadata = json.loads((MODELS / f'{task}.json').read_text())
    if task not in loaded:
        checkpoint = MODELS / f'{task}.pt'
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != metadata['sha256']:
            raise RuntimeError('Model integrity check failed.')
        torch.set_num_threads(2)
        loaded[task] = torch.jit.load(str(checkpoint), map_location='cpu').eval()
    return metadata, loaded[task]


def detect_cytology(path):
    """Whole-field detector: boxes are classified Bethesda categories, never diagnoses."""
    import torch
    from torchvision.ops import nms
    from torchvision.transforms.functional import pil_to_tensor
    metadata, net = load_model('cytology')
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    width, height = image.size
    if width * height > MAX_CYTOLOGY_PIXELS:
        raise ValueError('Cytology analysis supports images up to 16 megapixels. Crop or downscale the image.')
    with torch.inference_mode():
        output = net([pil_to_tensor(image).float() / 255])[1][0]
    boxes, scores, labels = output['boxes'], output['scores'], output['labels']
    keep = nms(boxes, scores, 0.5) if len(boxes) else []  # one box per cell, whichever class scored highest
    candidates = []
    for index in keep:
        x1, y1, x2, y2 = (float(v) for v in boxes[index])
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        if x2 > x1 and y2 > y1:
            candidates.append(dict(id=str(uuid4()), x=x1 / width, y=y1 / height, width=(x2 - x1) / width,
                                   height=(y2 - y1) / height, score=float(scores[index]),
                                   category=metadata['categories'][int(labels[index]) - 1]))
    return dict(model_id=metadata['id'], model_sha256=metadata['sha256'], checkpoint_sha256=metadata['checkpoint_sha256'],
                limitation=metadata['limitation'], source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                image_width=width, image_height=height, candidates=candidates, minimum_recorded_score=0.05)


def detect(path, task='histology'):
    if task == 'cytology':
        return detect_cytology(path)
    import torch
    from torchvision.transforms.functional import pil_to_tensor
    metadata, model = load_model('histology')
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    width, height = image.size
    if ((width + 447) // 448) * ((height + 447) // 448) > 25:
        raise ValueError('Analysis supports at most 25 tiles. Upload a smaller image or crop for this experimental model.')
    boxes = []
    with torch.inference_mode():
        for y in range(0, height, 448):
            for x in range(0, width, 448):
                tile = Image.new('RGB', (512, 512))
                left, top = max(0, x - 32), max(0, y - 32)
                right, bottom = min(width, x + 480), min(height, y + 480)
                tile.paste(image.crop((left, top, right, bottom)), (left - x + 32, top - y + 32))
                output = model([pil_to_tensor(tile).float() / 255])[1][0]
                for box, score in zip(output['boxes'].tolist(), output['scores'].tolist()):
                    x1, y1, x2, y2 = box
                    cx, cy = (x1 + x2) / 2 - 32 + x, (y1 + y2) / 2 - 32 + y
                    if score < 0.01 or not (x <= cx < min(x + 448, width) and y <= cy < min(y + 448, height)):
                        continue
                    x1, y1 = max(0, x1 - 32 + x), max(0, y1 - 32 + y)
                    x2, y2 = min(width, x2 - 32 + x), min(height, y2 - 32 + y)
                    if x2 > x1 and y2 > y1:
                        boxes.append(dict(id=str(uuid4()), x=x1 / width, y=y1 / height,
                                          width=(x2-x1)/width, height=(y2-y1)/height,
                                          score=score, category='Mitotic figure'))
    return dict(model_id=metadata['id'], model_sha256=metadata['sha256'],
                checkpoint_sha256=metadata['checkpoint_sha256'], limitation=LIMITATION,
                source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                image_width=width, image_height=height, candidates=boxes,
                minimum_recorded_score=0.01)


class StartAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: Literal['histology', 'cytology']
    request_id: UUID
    acknowledge_experimental: Literal[True]


def install(app, main):
    def response(row):
        return {**dict(row), 'result': json.loads(row['result'])}

    def work(run_id, case_id, upload_id, task):
        try:
            with main.database() as db:
                db.execute("UPDATE analysis_runs SET status='running',updated_at=? WHERE id=?", (stamp(), run_id))
            with main.stored_record(case_id, upload_id) as (_, path):
                result = detect(path, task)
            with main.database() as db:
                db.execute("UPDATE analysis_runs SET status='completed',result=?,updated_at=? WHERE id=?", (json.dumps(result), stamp(), run_id))
        except Exception as exc:
            logging.exception('Image analysis failed')
            message = str(exc) if isinstance(exc, ValueError) else 'Analysis failed. Retry or contact the administrator.'
            with main.database() as db:
                db.execute("UPDATE analysis_runs SET status='failed',error=?,updated_at=? WHERE id=?", (message, stamp(), run_id))
        finally:
            gate.release()

    @app.get('/analysis/models')
    def models():
        return {task: {'available': available(task), 'limitation': limitation(task)} for task in ('histology', 'cytology')}

    @app.get('/cases/{case_id}/uploads/{upload_id}/analysis')
    def runs(case_id: int, upload_id: int):
        main.image_dimensions(case_id, upload_id)
        with main.database() as db:
            return [response(row) for row in db.execute('SELECT * FROM analysis_runs WHERE upload_id=? ORDER BY created_at DESC LIMIT 20', (upload_id,))]

    @app.post('/cases/{case_id}/uploads/{upload_id}/analysis', status_code=202)
    def start(case_id: int, upload_id: int, payload: StartAnalysis, request: Request):
        dimensions = main.image_dimensions(case_id, upload_id)
        run_id = str(payload.request_id)
        with main.database() as db:
            row = db.execute('SELECT * FROM analysis_runs WHERE id=?', (run_id,)).fetchone()
            if row:
                if row['upload_id'] != upload_id or row['task'] != payload.task:
                    raise HTTPException(409, 'Request identifier already belongs to another analysis.')
                return response(row)
        if payload.task == 'cytology' and not available('cytology'):
            raise HTTPException(409, CYTOLOGY_UNAVAILABLE)
        if not available(payload.task):
            raise HTTPException(503, f'The {payload.task} model is not installed on this server.')
        if payload.task == 'histology' and ((dimensions[0]+447)//448)*((dimensions[1]+447)//448) > 25:
            raise HTTPException(413, 'Analysis supports at most 25 tiles. Use a smaller image.')
        if payload.task == 'cytology' and dimensions[0] * dimensions[1] > MAX_CYTOLOGY_PIXELS:
            raise HTTPException(413, 'Cytology analysis supports images up to 16 megapixels. Use a smaller image.')
        if not gate.acquire(blocking=False):
            raise HTTPException(409, 'An analysis is already running. Try again when it finishes.')
        try:
            with main.database() as db:
                db.execute('INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?)',
                           (run_id, upload_id, request.state.user['id'], payload.task, 'queued', '{}', '', stamp(), stamp()))
                main.security.audit(db, request.state.user['id'], 'analysis.start', run_id)
            executor.submit(work, run_id, case_id, upload_id, payload.task)
        except Exception:
            gate.release()
            raise
        with main.database() as db:
            return response(db.execute('SELECT * FROM analysis_runs WHERE id=?', (run_id,)).fetchone())
