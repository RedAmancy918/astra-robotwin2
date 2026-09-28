"""Make an annotated contact sheet of completed evaluation videos for visual review."""
from pathlib import Path
import json, sys, math
import cv2
from PIL import Image, ImageDraw

run = Path(sys.argv[1]).resolve()
rows = [json.loads(line) for line in (run / 'episodes.jsonl').read_text().splitlines()]
rows = [row for row in rows if row['counted']]
assert rows, 'No completed episodes'
out = run / 'final-frames'
out.mkdir(exist_ok=True)
sheet = Image.new('RGB', (4 * 320, math.ceil(len(rows) / 4) * 268), 'white')
draw = ImageDraw.Draw(sheet)
metadata = []
for i, row in enumerate(rows):
    video = Path(row['video'])
    cap = cv2.VideoCapture(str(video))
    assert cap.isOpened(), str(video)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    assert count >= row['actions'], (str(video), count, row['actions'])
    cap.set(cv2.CAP_PROP_POS_FRAMES, count - 1)
    ok, frame = cap.read()
    cap.release()
    assert ok, f'Cannot read final frame: {video}'
    frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    frame.save(out / f"seed-{row['seed']}.jpg", quality=95)
    x, y = (i % 4) * 320, (i // 4) * 268
    sheet.paste(frame.resize((320, 240)), (x, y + 28))
    draw.text((x + 6, y + 8), f"seed {row['seed']} | {'SUCCESS' if row['success'] else 'FAIL'} | {row['actions']} actions", fill='black')
    metadata.append({'episode_index': row['episode_index'], 'seed': row['seed'],
                     'frames': count, 'fps': fps, 'size_bytes': video.stat().st_size,
                     'final_frame_decoded': True})
sheet.save(run / 'final-frames.jpg', quality=95)
(run / 'video-validation.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps({'completed_videos_checked': len(metadata), 'contact_sheet': str(run / 'final-frames.jpg')}))
