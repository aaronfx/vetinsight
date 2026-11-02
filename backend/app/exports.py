"""Case-scoped COCO export of saved manual annotations; no training or inference."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import warnings
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from starlette.background import BackgroundTask


def export_case(main, case_id: int):
    # Read annotations and upload metadata together in one database snapshot.
    with main.database() as db:
        db.execute('BEGIN')
        main.require_case(db, case_id)
        assignment = main.dataset_assignment(db, case_id)
        rows = [dict(row) for row in db.execute('''SELECT u.*, a.revision, a.review_status,
            a.annotations, a.updated_at FROM uploads u LEFT JOIN annotation_sets a ON a.upload_id=u.id
            WHERE u.case_id=? AND u.content_type IN ('image/jpeg','image/png') ORDER BY u.id''', (case_id,))]
    eligible, skipped = [], []
    for row in rows:
        items = json.loads(row['annotations']) if row['annotations'] else []
        reason = None
        if row['review_status'] != 'Reviewed':
            reason = 'Image review is incomplete or annotations have not been saved.'
        elif not items:
            reason = 'No boxes saved; empty images are not assumed to be negative examples.'
        elif any(item['review_status'] != 'Reviewed' or item['category'].strip().casefold()
                 in ('unclassified', 'needs review') for item in items):
            reason = 'All boxes must be Reviewed and have a classified category.'
        if reason:
            skipped.append({'upload_id': row['id'], 'reason': reason})
        else:
            eligible.append((row, [main.Annotation.model_validate(item) for item in items]))
    if not eligible:
        raise HTTPException(422, 'No exportable images. Save an image as Reviewed with at least one Reviewed, classified box. Unclassified and Needs Review categories are excluded.')
    if len(eligible) > 200:
        raise HTTPException(413, 'Export supports at most 200 reviewed images per case.')
    categories = sorted({item.category for _, items in eligible for item in items})
    category_ids = {name: index for index, name in enumerate(categories, 1)}
    coco = {'info': {'description': 'VetInsight saved manual bounding boxes', 'version': '1'},
            'images': [], 'annotations': [],
            'categories': [{'id': value, 'name': name} for name, value in category_ids.items()]}
    manifest = {'schema_version': 1, 'case_id': case_id, 'exported_at': main.now(),
                'format': 'COCO bounding boxes', 'images': [], 'skipped_images': skipped,
                'policy': 'Saved Reviewed images with nonempty, fully Reviewed classified boxes only.',
                'split': assignment['split'] if assignment['split'] != 'unassigned' else None,
                'dataset_assignment': assignment}
    workspace = TemporaryDirectory(prefix='vetinsight-export-')
    try:
        archive_path = Path(workspace.name) / 'export.zip'
        total_pixels = 0
        with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
            for row, items in eligible:
                with main.stored_record(case_id, row['id']) as (_, source):
                    width, height = main.image_dimensions_for_file(row, source)
                    total_pixels += width * height
                    if total_pixels > 100_000_000:
                        raise HTTPException(413, 'Export exceeds the 100 million decoded pixel limit.')
                    filename = f'images/case-{case_id}-upload-{row["id"]}.png'
                    image_path = Path(workspace.name) / 'image.png'
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter('error', Image.DecompressionBombWarning)
                            with Image.open(source) as image:
                                # Bake orientation into pixels and strip embedded metadata.
                                oriented = ImageOps.exif_transpose(image).convert('RGBA')
                                clean = Image.new('RGB', oriented.size, 'white')
                                clean.paste(oriented, mask=oriented.getchannel('A'))
                                clean.save(image_path, 'PNG')
                    except (OSError, ValueError, SyntaxError):
                        raise HTTPException(422, f'Image upload {row["id"]} cannot be decoded for export.')
                    archive.write(image_path, filename)
                    coco['images'].append({'id': row['id'], 'file_name': filename, 'width': width, 'height': height})
                    for item in items:
                        bbox = [item.x * width, item.y * height, item.width * width, item.height * height]
                        coco['annotations'].append({'id': len(coco['annotations']) + 1, 'image_id': row['id'],
                            'category_id': category_ids[item.category], 'bbox': bbox,
                            'area': bbox[2] * bbox[3], 'iscrowd': 0})
                    manifest['images'].append({'upload_id': row['id'], 'case_id': case_id, 'file_name': filename,
                        'split': manifest['split'],
                        'revision': row['revision'], 'updated_at': row['updated_at'],
                        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'export_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(),
                        'annotations': [item.model_dump(mode='json') for item in items]})
                    image_path.unlink()
                    if archive_path.stat().st_size > 256 * 1024 * 1024:
                        raise HTTPException(413, 'Export exceeds the 256 MiB archive limit.')
            archive.writestr('annotations.json', json.dumps(coco, ensure_ascii=False, indent=2))
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', 'VetInsight manual annotation export\n\n'
                'annotations.json: COCO detection boxes [x, y, width, height] in pixels.\n'
                'images/: RGB PNG copies with EXIF orientation baked into pixels; metadata stripped; transparency composited on white.\n'
                'manifest.json: case/upload IDs, saved revisions, original normalized boxes, review states, notes and hashes.\n'
                'No patient name, species, case notes or original filenames are added. Annotation notes and image pixels may still contain identifying information. This is not an anonymization guarantee.\n'
                'Empty images are excluded; review does not establish exhaustive labeling or clinical validity.\n'
                'manifest.json records the saved case split and assignment revision at export time (null split means unassigned).\n'
                'All images from one case inherit the same split. Re-export after changing an assignment; old archives are unchanged.\n'
                'Repeated patients or duplicate images across different cases require additional grouping before training.\n'
                'Category IDs are sorted within this archive; remap by category name when merging exports.\n'
                'No model predictions, confidence scores, masks or diagnoses are generated.\n')
        if archive_path.stat().st_size > 256 * 1024 * 1024:
            raise HTTPException(413, 'Export exceeds the 256 MiB archive limit.')
        return FileResponse(archive_path, media_type='application/zip',
            filename=f'vetinsight-case-{case_id}-coco.zip', headers=main.DELIVERY_HEADERS,
            background=BackgroundTask(workspace.cleanup))
    except BaseException:
        workspace.cleanup()
        raise
