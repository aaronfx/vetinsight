"""Local case management API. Uploaded records are stored, never analyzed."""

from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
import logging
import json
import os
import re
from pathlib import Path
import sqlite3
from typing import Annotated, Literal
from uuid import UUID, uuid4
import warnings

from fastapi import FastAPI, File, HTTPException, Path as ApiPath, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from PIL import Image, UnidentifiedImageError
from . import security
from . import analysis
from . import database as persistence
from .cloud_config import runtime_settings
from .object_storage import ObjectStorage
from tempfile import TemporaryDirectory

DATA_DIR = Path(os.environ.get("VETINSIGHT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")).resolve()
STATIC_DIR = Path(os.environ['VETINSIGHT_STATIC_DIR']).resolve() if os.environ.get('VETINSIGHT_STATIC_DIR') else None
CLOUD = runtime_settings()
STORE = ObjectStorage(DATA_DIR, CLOUD)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
CaseId = Annotated[int, ApiPath(gt=0)]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    with persistence.connect(DATA_DIR, CLOUD.database_url, CLOUD.schema) as connection:
        yield connection


def initialize_database(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            species TEXT NOT NULL,
            notes TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id),
            filename TEXT NOT NULL,
            storage_name TEXT NOT NULL UNIQUE,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS uploads_case_id ON uploads(case_id);
        CREATE TABLE IF NOT EXISTS annotation_sets (
            upload_id INTEGER PRIMARY KEY REFERENCES uploads(id),
            revision INTEGER NOT NULL,
            review_status TEXT NOT NULL,
            annotations TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dataset_assignments (
            case_id INTEGER PRIMARY KEY REFERENCES cases(id),
            split TEXT NOT NULL CHECK(split IN ('unassigned','train','validation','test')),
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    security.initialize(db)
    analysis.initialize(db)
    db.protect_schema()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and not os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') and not CLOUD.database_url:
        raise RuntimeError('Attach a persistent Railway volume before starting local SQLite storage.')
    if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') and not CLOUD.database_url:
        mount = Path(os.environ['RAILWAY_VOLUME_MOUNT_PATH']).resolve()
        if not DATA_DIR.is_relative_to(mount):
            raise RuntimeError('SQLite data directory must be inside the persistent volume.')
    (DATA_DIR / 'uploads').mkdir(parents=True, exist_ok=True)
    with database() as db:
        initialize_database(db)
    STORE.ensure_private_bucket()
    yield


app = FastAPI(title="VetInsight Case API", version="1.0.0", lifespan=lifespan)
import sys
analysis.install(app, sys.modules[__name__])
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"] + ([os.environ['VETINSIGHT_FRONTEND_ORIGIN']] if os.environ.get('VETINSIGHT_FRONTEND_ORIGIN') else [])
if os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
    ALLOWED_ORIGINS.append('https://' + os.environ['RAILWAY_PUBLIC_DOMAIN'])
security.install(app, database, ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-VetInsight-Request"],
)

if STATIC_DIR is not None:
    app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='frontend-assets')

    @app.get('/', include_in_schema=False)
    @app.get('/research', include_in_schema=False)
    def frontend_index():
        return FileResponse(STATIC_DIR / 'index.html')

    @app.get('/favicon.svg', include_in_schema=False)
    def frontend_favicon():
        return FileResponse(STATIC_DIR / 'favicon.svg')

    @app.get('/icons.svg', include_in_schema=False)
    def frontend_icons():
        return FileResponse(STATIC_DIR / 'icons.svg')


@app.get('/cases/{case_id}/exports/coco')
def export_annotations(case_id: CaseId):
    import sys
    from .exports import export_case
    return export_case(sys.modules[__name__], case_id)


@app.exception_handler(persistence.DatabaseError)
@app.exception_handler(sqlite3.Error)
async def storage_error(_request, exc):
    logging.exception("Database operation failed", exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Storage is unavailable. Please try again."})


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # Validation responses must never echo credentials or clinical request bodies.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']} for error in exc.errors()
    ]})


@app.exception_handler(OSError)
async def file_error(_request, exc):
    logging.exception("File operation failed", exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "File storage is unavailable. Please try again."})


class CaseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_name: str = Field(min_length=1, max_length=120)
    species: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=10000)


class CaseSummary(CaseCreate):
    id: int
    created_at: str
    upload_count: int = 0
    image_count: int = 0


class UploadInfo(BaseModel):
    id: int
    case_id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: str
    download_url: str
    preview_url: str
    text_url: str


class CaseDetail(CaseSummary):
    uploads: list[UploadInfo]


def require_case(db, case_id: int):
    row = db.execute("""SELECT cases.*,
        (SELECT COUNT(*) FROM uploads WHERE case_id=cases.id) AS upload_count,
        (SELECT COUNT(*) FROM uploads WHERE case_id=cases.id AND content_type IN ('image/jpeg','image/png')) AS image_count
        FROM cases WHERE id = ?""", (case_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Case not found.")
    return dict(row)


DatasetSplit = Literal['unassigned', 'train', 'validation', 'test']


class DatasetAssignmentSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    split: DatasetSplit
    revision: int = Field(ge=0, strict=True)


class DatasetAssignment(DatasetAssignmentSave):
    case_id: int
    updated_at: str | None


def dataset_assignment(db, case_id: int):
    row = db.execute('SELECT * FROM dataset_assignments WHERE case_id=?', (case_id,)).fetchone()
    return dict(row) if row else {'case_id': case_id, 'split': 'unassigned', 'revision': 0, 'updated_at': None}


@app.get('/cases/{case_id}/dataset-assignment', response_model=DatasetAssignment)
def get_dataset_assignment(case_id: CaseId):
    with database() as db:
        require_case(db, case_id)
        return dataset_assignment(db, case_id)


@app.put('/cases/{case_id}/dataset-assignment', response_model=DatasetAssignment)
def save_dataset_assignment(case_id: CaseId, payload: DatasetAssignmentSave, request: Request):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        require_case(db, case_id)
        current = dataset_assignment(db, case_id)
        if payload.revision != current['revision']:
            raise HTTPException(409, 'Dataset assignment changed in another session. Reload the saved assignment before changing it.')
        if payload.split != current['split']:
            db.execute('''INSERT INTO dataset_assignments (case_id, split, revision, updated_at)
                VALUES (?, ?, ?, ?) ON CONFLICT(case_id) DO UPDATE SET
                split=excluded.split, revision=excluded.revision, updated_at=excluded.updated_at''',
                (case_id, payload.split, current['revision'] + 1, now()))
        security.audit(db, request.state.user['id'], 'workspace.put', str(request.url.path))
        return dataset_assignment(db, case_id)


def upload_info(row):
    result = dict(row)
    result.pop("storage_name")
    result["download_url"] = f"/cases/{result['case_id']}/uploads/{result['id']}"
    result["preview_url"] = result["download_url"] + "/preview"
    result["text_url"] = result["download_url"] + "/text"
    return result


@app.get("/health")
def health():
    with database() as db:
        db.execute("SELECT COUNT(*) FROM cases").fetchone()
    return {"status": "ok", "database": "ok"}


@app.post("/cases", response_model=CaseDetail, status_code=201)
def create_case(payload: CaseCreate, request: Request):
    with database() as db:
        cursor = db.execute(
            "INSERT INTO cases (patient_name, species, notes, created_at) VALUES (?, ?, ?, ?)",
            (payload.patient_name, payload.species, payload.notes, now()),
        )
        security.audit(db, request.state.user['id'], 'workspace.post', f'/cases/{cursor.lastrowid}')
        return {**require_case(db, cursor.lastrowid), "uploads": []}


@app.get("/cases", response_model=list[CaseSummary])
def list_cases(limit: Annotated[int, Query(ge=1, le=100)] = 100,
               offset: Annotated[int, Query(ge=0)] = 0,
               search: Annotated[str, Query(max_length=120)] = "",
               species: Annotated[str, Query(max_length=80)] = ""):
    escaped = search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    identifier = re.fullmatch(r'(?:CASE-)?0*(\d+)', search.strip().lstrip('#'), re.IGNORECASE)
    with database() as db:
        return [dict(row) for row in db.execute(
            """SELECT cases.*,
                (SELECT COUNT(*) FROM uploads WHERE case_id=cases.id) AS upload_count,
                (SELECT COUNT(*) FROM uploads WHERE case_id=cases.id AND content_type IN ('image/jpeg','image/png')) AS image_count
                FROM cases WHERE (LOWER(patient_name) LIKE LOWER(?) ESCAPE '\\' OR CAST(id AS TEXT)=?)
                AND (?='' OR species=?) ORDER BY id DESC LIMIT ? OFFSET ?""",
            (f"%{escaped}%", str(int(identifier[1])) if identifier else '', species, species, limit, offset)
        )]


@app.get("/dashboard")
def dashboard():
    with database() as db:
        counts = db.execute("""SELECT COUNT(*) AS upload_count,
            COALESCE(SUM(CASE WHEN content_type='application/pdf' THEN 1 ELSE 0 END),0) AS document_count,
            COALESCE(SUM(CASE WHEN content_type IN ('image/jpeg','image/png') THEN 1 ELSE 0 END),0) AS image_count FROM uploads""").fetchone()
        annotations = [item for row in db.execute("SELECT annotations FROM annotation_sets") for item in json.loads(row[0])]
        return {**dict(counts), "case_count": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                "annotation_count": len(annotations),
                "needs_review_count": sum(item['review_status'] == 'Needs Review' for item in annotations),
                "species": [row[0] for row in db.execute("SELECT DISTINCT species FROM cases ORDER BY species")]}


@app.get("/cases/{case_id}", response_model=CaseDetail)
def view_case(case_id: CaseId):
    with database() as db:
        result = require_case(db, case_id)
        result["uploads"] = [upload_info(row) for row in db.execute(
            "SELECT * FROM uploads WHERE case_id = ? ORDER BY id", (case_id,)
        )]
        return result


@app.post("/cases/{case_id}/uploads", response_model=UploadInfo, status_code=201)
def upload_record(case_id: CaseId, file: Annotated[UploadFile, File()], request: Request):
    destination = None
    committed = False
    remote_written = False
    workspace = None
    try:
        with database() as db:
            require_case(db, case_id)
        filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
        if not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename):
            raise HTTPException(400, "Provide a valid filename of at most 255 characters.")
        extension = Path(filename).suffix.lower()
        types = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        if extension not in types:
            raise HTTPException(415, "Only PDF, JPG/JPEG and PNG files are supported.")
        header = file.file.read(8)
        if not header:
            raise HTTPException(400, "The uploaded file is empty.")
        valid = (extension == ".pdf" and header.startswith(b"%PDF-")) or (
            extension in (".jpg", ".jpeg") and header.startswith(b"\xff\xd8\xff")
        ) or (extension == ".png" and header == b"\x89PNG\r\n\x1a\n")
        if not valid:
            raise HTTPException(415, "File contents do not match the PDF/JPG/PNG extension.")
        storage_name = f"{uuid4().hex}{extension}"
        if STORE.remote:
            workspace = TemporaryDirectory(prefix='vetinsight-upload-')
            destination = Path(workspace.name) / storage_name
        else:
            destination = DATA_DIR / 'uploads' / storage_name
        size = len(header)
        with destination.open("xb") as output:
            output.write(header)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Files must be 20 MiB or smaller.")
                output.write(chunk)
        if STORE.remote:
            STORE.upload(storage_name, destination, types[extension])
            remote_written = True
        with database() as db:
            cursor = db.execute(
                "INSERT INTO uploads (case_id, filename, storage_name, content_type, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (case_id, filename, storage_name, types[extension], size, now()),
            )
            result = upload_info(db.execute("SELECT * FROM uploads WHERE id = ?", (cursor.lastrowid,)).fetchone())
            security.audit(db, request.state.user['id'], 'workspace.post', f'/cases/{case_id}/uploads/{cursor.lastrowid}')
        committed = True
        return result
    finally:
        file.file.close()
        if destination is not None and not committed:
            destination.unlink(missing_ok=True)
        if remote_written and not committed:
            try:
                STORE.delete(storage_name)
            except Exception:
                logging.error('Remote upload cleanup failed for storage object %s', storage_name)
        if workspace is not None:
            workspace.cleanup()


def record_info(case_id: int, upload_id: int):
    with database() as db:
        require_case(db, case_id)
        row = db.execute('SELECT * FROM uploads WHERE case_id=? AND id=?', (case_id, upload_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Upload not found for this case.')
    STORE.checked_name(row['storage_name'])
    if not STORE.remote and not (DATA_DIR / 'uploads' / row['storage_name']).is_file():
        raise HTTPException(404, 'Uploaded file is missing from storage.')
    return dict(row)


@contextmanager
def stored_record(case_id: int, upload_id: int):
    row = record_info(case_id, upload_id)
    with STORE.local_copy(row['storage_name']) as path:
        yield row, path


DELIVERY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}


@app.get("/cases/{case_id}/uploads/{upload_id}")
def download_record(case_id: CaseId, upload_id: Annotated[int, ApiPath(gt=0)]):
    return STORE.response(record_info(case_id, upload_id), DELIVERY_HEADERS)



@app.get("/cases/{case_id}/uploads/{upload_id}/preview")
def preview_record(case_id: CaseId, upload_id: Annotated[int, ApiPath(gt=0)]):
    row = record_info(case_id, upload_id)
    types = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
    media_type = types.get(Path(row['storage_name']).suffix.lower())
    if media_type is None or row['content_type'] != media_type:
        raise HTTPException(415, 'Preview is unsupported for this file type. Use Download.')
    return STORE.response(row, DELIVERY_HEADERS, inline=True)



class TextPage(BaseModel):
    page_number: int
    text: str
    status: str


class DocumentText(BaseModel):
    status: str
    page_count: int
    pages: list[TextPage]


@app.get("/cases/{case_id}/uploads/{upload_id}/text", response_model=DocumentText)
def extract_document_text(case_id: CaseId, upload_id: Annotated[int, ApiPath(gt=0)]):
    with stored_record(case_id, upload_id) as (row, path):
        return extract_document_file(row, path, upload_id)


def extract_document_file(row, path, upload_id):
    if row["content_type"] != "application/pdf" or path.suffix.lower() != ".pdf":
        raise HTTPException(415, "Text extraction is supported only for PDFs.")
    try:
        with path.open("rb") as source:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise HTTPException(422, "Text extraction is unsupported for encrypted PDFs.")
            if len(reader.pages) == 0:
                raise HTTPException(422, "This PDF has no pages.")
            if len(reader.pages) > 500:
                raise HTTPException(413, "Text extraction supports at most 500 pages. Preview or download the original.")
            pages = []
            total_characters = 0
            for number, page in enumerate(reader.pages, start=1):
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > 10 * 1024 * 1024:
                    raise HTTPException(413, "This PDF page is too large for text extraction. Preview or download the original.")
                text = page.extract_text() or ""
                total_characters += len(text)
                if total_characters > 2_000_000:
                    raise HTTPException(413, "Extracted text exceeds the supported size. Download the original.")
                pages.append({"page_number": number, "text": text,
                              "status": "extracted" if text.strip() else "ocr_required"})
    except (HTTPException, OSError):
        raise
    except Exception:
        logging.exception("PDF text extraction failed for upload %s", upload_id)
        raise HTTPException(422, "Text extraction failed. The PDF may be damaged or unsupported. Download the original.")
    with_text = sum(page["status"] == "extracted" for page in pages)
    status = "ocr_required" if not with_text else "extracted" if with_text == len(pages) else "partial"
    return {"status": status, "page_count": len(pages), "pages": pages}


ReviewStatus = Literal['Needs Review', 'In Progress', 'Reviewed']


class Annotation(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    id: UUID
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    category: str = Field(default='Unclassified', min_length=1, max_length=80)
    review_status: ReviewStatus = 'Needs Review'
    notes: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def bounds(self):
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError('Bounding box must stay within the image.')
        return self


class AnnotationSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    review_status: ReviewStatus = 'Needs Review'
    annotations: list[Annotation] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique_ids_and_review(self):
        if len({item.id for item in self.annotations}) != len(self.annotations):
            raise ValueError('Annotation IDs must be unique within an image.')
        if self.review_status == 'Reviewed' and any(item.review_status != 'Reviewed' for item in self.annotations):
            raise ValueError('Review all annotations before marking the image Reviewed.')
        return self


class AnnotationSet(AnnotationSave):
    upload_id: int
    case_id: int
    image_width: int
    image_height: int
    updated_at: str | None


def image_dimensions(case_id: int, upload_id: int):
    with stored_record(case_id, upload_id) as (row, path):
        return image_dimensions_for_file(row, path)


def image_dimensions_for_file(row, path):
    if row['content_type'] not in ('image/jpeg', 'image/png'):
        raise HTTPException(415, 'Cytology annotations require a JPG or PNG image.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.format not in ('JPEG', 'PNG'):
                    raise HTTPException(415, 'Unsupported image format.')
                # Match the browser's EXIF-oriented display coordinates.
                width, height = image.size
                if image.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
                return width, height
    except (UnidentifiedImageError, SyntaxError, ValueError):
        raise HTTPException(422, 'The image cannot be decoded. Upload a valid JPG or PNG.')
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(413, 'This image is too large for the cytology workspace.')


def annotation_response(case_id, upload_id, dimensions, row=None):
    return {'case_id': case_id, 'upload_id': upload_id,
            'image_width': dimensions[0], 'image_height': dimensions[1],
            'revision': row['revision'] if row else 0,
            'review_status': row['review_status'] if row else 'Needs Review',
            'annotations': json.loads(row['annotations']) if row else [],
            'updated_at': row['updated_at'] if row else None}


@app.get('/cases/{case_id}/uploads/{upload_id}/annotations', response_model=AnnotationSet)
def get_annotations(case_id: CaseId, upload_id: Annotated[int, ApiPath(gt=0)]):
    dimensions = image_dimensions(case_id, upload_id)
    with database() as db:
        row = db.execute('SELECT * FROM annotation_sets WHERE upload_id=?', (upload_id,)).fetchone()
        return annotation_response(case_id, upload_id, dimensions, row)


@app.put('/cases/{case_id}/uploads/{upload_id}/annotations', response_model=AnnotationSet)
def save_annotations(case_id: CaseId, upload_id: Annotated[int, ApiPath(gt=0)], payload: AnnotationSave, request: Request):
    dimensions = image_dimensions(case_id, upload_id)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM annotation_sets WHERE upload_id=?', (upload_id,)).fetchone()
        revision = row['revision'] if row else 0
        if payload.revision != revision:
            raise HTTPException(409, 'Annotations changed in another session. Reload saved annotations before editing again.')
        db.execute('''INSERT INTO annotation_sets (upload_id, revision, review_status, annotations, updated_at)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(upload_id) DO UPDATE SET
            revision=excluded.revision, review_status=excluded.review_status,
            annotations=excluded.annotations, updated_at=excluded.updated_at''',
            (upload_id, revision + 1, payload.review_status,
             json.dumps([item.model_dump(mode='json') for item in payload.annotations]), now()))
        security.audit(db, request.state.user['id'], 'workspace.put', str(request.url.path))
        row = db.execute('SELECT * FROM annotation_sets WHERE upload_id=?', (upload_id,)).fetchone()
        return annotation_response(case_id, upload_id, dimensions, row)
