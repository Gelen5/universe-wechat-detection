"""Render with the installed weChat-autoCreate Skill.

The application owns the preview shell, but the article fragment is rendered by
the installed Skill's converter and theme engine.  A small trace file makes the
actual renderer and modules auditable from the workbench session.
"""
import html
import json
import sys
from pathlib import Path


def main():
    root, source, theme_name = sys.argv[1:4]
    sys.path.insert(0, root)
    sys.path.insert(0, str(Path(root) / 'scripts'))
    from toolkit.converter import MarkdownConverter
    from toolkit.theme import apply_theme, load_theme
    from toolkit.recommendation_quality import check_article_file
    from leaf_autofix import LeafWrapper
    import yaml

    path = Path(source)
    report = check_article_file(str(path), strict=True)
    path.with_suffix('.quality.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    content = path.read_text(encoding='utf-8')
    metadata = {}
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) == 3:
            metadata = yaml.safe_load(parts[1]) or {}
            content = parts[2]
    converter = MarkdownConverter()
    rendered = converter.convert(content)
    rendered = apply_theme(rendered, load_theme(theme_name))
    # The latest Skill's compliance contract requires every CJK text node to
    # have a leaf wrapper. Reuse its official fixer on the rendered fragment.
    leaf_wrapper = LeafWrapper()
    leaf_wrapper.feed(rendered)
    leaf_wrapper.close()
    rendered = leaf_wrapper.result()
    modules = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith(":::"):
            continue
        match = stripped.removeprefix(":::").strip()
        if match and not match.startswith("/"):
            modules.append(match.split("[", 1)[0].strip())
    path.with_suffix('.render.json').write_text(json.dumps({
        "skill": "weChat-autoCreate",
        "renderer": "toolkit.converter.MarkdownConverter",
        "theme_engine": "toolkit.theme.load_theme+apply_theme",
        "source": "Markdown + :::module DSL",
        "leaf_wrapper": "scripts.leaf_autofix.LeafWrapper",
        "theme": theme_name,
        "modules": modules,
        "quality_gate": "toolkit.recommendation_quality.check_article_file",
        "quality_gate_blocked": bool(report.get("blocked")),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    document = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title><style>body{max-width:680px;margin:0 auto;padding:20px;font-family:system-ui,sans-serif}button{display:block;margin:0 auto 20px;padding:12px 20px}</style></head>
<body><button id="copy-article">复制到公众号</button><main id="article-content">__CONTENT__</main>
<script>document.getElementById('copy-article').onclick=async function(){
const el=document.getElementById('article-content');
try{await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([el.innerHTML],{type:'text/html'}),'text/plain':new Blob([el.innerText],{type:'text/plain'})})]);this.textContent='已复制';}
catch(e){const r=document.createRange();r.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(r);if(document.execCommand('copy'))this.textContent='已复制';s.removeAllRanges();}
};</script></body></html>'''
    document = document.replace('__TITLE__', html.escape(str(metadata.get('title', 'Preview')))).replace('__CONTENT__', rendered)
    path.with_name(path.stem + '_preview.html').write_text(document, encoding='utf-8')


if __name__ == '__main__':
    main()
