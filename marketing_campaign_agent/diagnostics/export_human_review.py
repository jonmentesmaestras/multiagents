"""Export saved classifications for human inspection without modifying ADK state."""
import json
import sqlite3
from pathlib import Path
from collections import Counter
from html import escape
from urllib.parse import urlencode
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

def decode(value):
    return json.loads(value, strict=False) if isinstance(value, str) else value

def sessions():
    with sqlite3.connect((ROOT / '.adk/session.db').as_uri() + '?mode=ro', uri=True) as db:
        return [(sid, decode(raw), updated) for sid, raw, updated in db.execute(
            'select id,state,update_time from sessions order by update_time desc limit 20')]

def export(sid, state, updated):
    rows = decode(state.get('youtube_comments_classified') or [])
    relevant = [x for x in rows if x.get('decision', x.get('categoria')) in {'deseo', 'problema'}]
    ids = [x.get('comment_id') for x in relevant]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError('Hay identificadores ausentes o duplicados en la clasificación')
    source = {}
    for video in decode(state.get('youtube_comments_collected') or []):
        for comment in video.get('3_months_comments', []):
            if comment.get('comment_id'):
                source[comment['comment_id']] = {**comment, 'video_href': comment.get('video_href') or video.get('video_href', '')}
    exported = []
    for row in relevant:
        original = source.get(row['comment_id'])
        if original is None or row.get('Msg') != original.get('Msg'):
            raise ValueError('El comentario no coincide con la fuente: ' + row['comment_id'])
        href = original['video_href']
        exported.append({**row, 'published_at': original.get('published_at'),
                         'video_href': href, 'comment_url': href + ('&' if '?' in href else '?') + urlencode({'lc': row['comment_id']}),
                         'revision_humana': 'pendiente', 'observacion_humana': ''})
    counts = Counter(x.get('decision', x.get('categoria')) for x in exported)
    payload = {'session_id': sid, 'session_updated_at_utc': datetime.fromtimestamp(updated, timezone.utc).isoformat(),
               'exported_at_utc': datetime.now(timezone.utc).isoformat(), 'total_decisiones': len(rows),
               'total_para_revision': len(exported), 'conteos': dict(counts),
               'estado_revision_humana': 'pendiente', 'comentarios': exported,
               'pendientes_revision': [x for x in rows if x.get('decision') == 'requiere_revision']}
    folder = ROOT / 'docs' / 'revision_humana' / sid
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / 'comentarios_deseos_problemas.json'
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    cards = []
    for i, row in enumerate(exported, 1):
        decision = row.get('decision', row.get('categoria'))
        category = row.get(decision) or row.get('category_id') or 'No registrada'
        reason = row.get('reason') or row.get('razon') or row.get('evidence') or 'No registrada por el clasificador'
        cards.append(f'<article><h2>{i}. {escape(decision.title())} — {escape(str(category))}</h2>'
                     f'<p><strong>Autor:</strong> {escape(row.get("Author") or "No registrado")} · '
                     f'<strong>Fecha:</strong> {escape(row.get("published_at") or "No registrada")}</p>'
                     f'<blockquote>{escape(row.get("Msg", ""))}</blockquote>'
                     f'<p><strong>Justificación guardada:</strong> {escape(str(reason))}</p>'
                     f'<p><a href="{escape(row["comment_url"], quote=True)}">Abrir comentario en YouTube</a> · '
                     f'ID: {escape(row["comment_id"])}</p>'
                     '<p class="review">Revisión humana pendiente: □ Confirmar □ Rechazar □ Reclasificar<br>Observación: ______________________________________________</p></article>')
    html_path = folder / 'comentarios_deseos_problemas.html'
    html_path.write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>Revisión humana de comentarios</title>'
                        '<style>body{font:16px/1.55 system-ui;max-width:1050px;margin:40px auto;padding:0 24px;color:#17212b}'
                        'article{border-top:1px solid #ccd4dc;padding:18px 0;break-inside:avoid}h2{font-size:19px}'
                        'blockquote{margin:12px 0;white-space:pre-wrap;background:#f4f6f8;padding:16px;overflow-wrap:anywhere}'
                        'a{color:#125c9e}.review{color:#45505c}@media print{body{font-size:11pt;margin:0}}</style>'
                        '<h1>Revisión humana de deseos y problemas</h1>'
                        f'<p><strong>{len(exported)} comentarios: {counts["deseo"]} deseos y {counts["problema"]} problemas.</strong> '
                        f'Seleccionados de {len(rows)} decisiones guardadas.</p>'
                        '<p>La clasificación fue realizada automáticamente. Todos los registros están pendientes de revisión humana. '
                        'Comprueba si el texto respalda la categoría asignada antes de confirmar la conclusión de mercado.</p>'
                        f'<p>Sesión: {escape(sid)}. Los textos e identificadores se cotejaron con la recolección guardada.</p>'
                        + ''.join(cards) + '</html>', encoding='utf-8')
    assert len(json.loads(json_path.read_text(encoding='utf-8'))['comentarios']) == len(exported)
    assert html_path.read_text(encoding='utf-8').count('<article>') == len(exported)
    return {'html': str(html_path), 'json': str(json_path), 'counts': dict(counts), 'source_texts_verified': len(exported)}

if __name__ == '__main__':
    for sid, state, updated in sessions():
        rows = decode(state.get('youtube_comments_classified') or [])
        if any(x.get('decision', x.get('categoria')) in {'deseo', 'problema'} for x in rows):
            print(json.dumps(export(sid, state, updated), ensure_ascii=True))
            break
    else:
        raise SystemExit('No hay clasificaciones guardadas para exportar')
