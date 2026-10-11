"""Render source relationships independently of the podcast playback timeline."""
from html import escape as esc
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse


def time_link(url, seconds):
    p=urlparse(url);q=dict(parse_qsl(p.query));q['t']=str(int(seconds))
    return urlunparse(p._replace(query=urlencode(q)))


def references_html(m):
    items=[]
    for r in m.get('references',[]):
        cues=''.join('<li><a target="_blank" rel="noopener" href="'+esc(time_link(r['url'],c['start']),quote=True)+'">原访谈 '+f"{c['start']//60:02}:{c['start']%60:02}"+'</a><p>'+esc(c['summary'])+'</p></li>' for c in r.get('cues',[]))
        items.append('<article class="reference-card"><small>'+esc(r['relationship'])+'</small><h4><a target="_blank" rel="noopener" href="'+esc(r['url'],quote=True)+'">'+esc(r['title'])+' ↗</a></h4><p>'+esc(r['text'])+'</p>'+('<ul class="evidence-cues">'+cues+'</ul>' if cues else '')+'<small>'+esc(r['coverage_note'])+'</small></article>')
    return '<div class="references">'+''.join(items)+'</div>' if items else ''


def illustration_html(m):
    x=m.get('illustration')
    return '<figure class="editorial-figure"><img src="'+esc(x['url'],quote=True)+'" alt="'+esc(x['caption'],quote=True)+'"><figcaption>'+esc(x['caption'])+'</figcaption></figure>' if x else ''
