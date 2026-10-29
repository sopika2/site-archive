"""JavaScript evaluated inside the page to collect links and visible text in reading order."""

COLLECT_LINKS_JS = r"""
() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
  href: a.getAttribute('href'),
  abs: a.href,
  text: (a.innerText || a.getAttribute('aria-label') || a.title || (a.querySelector('img') ? a.querySelector('img').alt : '') || '').replace(/\s+/g, ' ').trim()
}))
"""

# Options: includeHidden (bool). Returns [{type, text, region}, ...]
COLLECT_TEXT_JS = r"""
(opts) => {
  const includeHidden = !!(opts && opts.includeHidden);
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','IFRAME','HEAD','CANVAS','VIDEO','AUDIO','OBJECT','EMBED','SELECT','OPTION','TEXTAREA','MAP']);
  const INLINE = new Set(['SPAN','STRONG','EM','B','I','U','S','SMALL','CODE','BR','SUP','SUB','ABBR','TIME','MARK','Q','CITE','KBD','VAR','SAMP','DFN','DEL','INS','WBR','BDI','BDO','FONT','LABEL','IMG','PICTURE','SOURCE','INPUT','A','BUTTON']);
  const BLOCK_TEXT = new Set(['P','LI','BLOCKQUOTE','FIGCAPTION','TD','TH','DT','DD','PRE','SUMMARY','ADDRESS','CAPTION','LEGEND']);
  const NESTED_BLOCK_SEL = 'p,ul,ol,div,section,article,aside,nav,header,footer,main,h1,h2,h3,h4,h5,h6,table,blockquote,figure,form,fieldset,details,dl';
  const out = [];
  const seenNodes = new Set();

  const clean = (t) => (t || '').replace(/ /g, ' ').replace(/[ \t\r\f\v]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim();
  const push = (type, text, region) => { text = clean(text); if (text) out.push({ type, text, region }); };

  const isVisible = (el) => {
    if (includeHidden) return true;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    if (el.hidden) return false;
    return true;
  };
  const textOf = (el) => includeHidden ? el.textContent : el.innerText;
  const regionOf = (el, cur) => {
    const tag = el.tagName, role = (el.getAttribute('role') || '').toLowerCase();
    if (tag === 'NAV' || role === 'navigation') return 'nav';
    if (tag === 'HEADER' || role === 'banner') return cur || 'header';
    if (tag === 'FOOTER' || role === 'contentinfo') return 'footer';
    return cur;
  };
  const looksLikeButton = (el) => {
    const cls = (el.className && typeof el.className === 'string') ? el.className.toLowerCase() : '';
    if (/\b(btn|button|cta)\b|btn-|button-|-btn|-button|-cta|cta-/.test(cls)) return true;
    if ((el.getAttribute('role') || '').toLowerCase() === 'button') return true;
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
    const border = parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none';
    return (cs.display !== 'inline') && (hasBg || border);
  };
  const classify = (el, region) => {
    const tag = el.tagName;
    if (tag === 'BUTTON' || (tag === 'INPUT' && /^(submit|button|reset)$/i.test(el.type))) return 'button';
    if (tag === 'A') {
      if (region === 'nav' || region === 'header' || region === 'footer') return 'link';
      return looksLikeButton(el) ? 'cta' : 'link';
    }
    return null;
  };
  const singleActionChild = (el) => {
    const actions = el.querySelectorAll('a,button,input[type=submit],input[type=button]');
    if (actions.length !== 1) return null;
    const a = actions[0];
    if (clean(textOf(a)) === clean(textOf(el))) return a;
    return null;
  };
  const inlineText = (node) => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1) return '';
    if (SKIP.has(node.tagName)) return '';
    if (!isVisible(node)) return '';
    if (node.tagName === 'IMG') return node.alt ? ' ' : '';
    if (node.tagName === 'INPUT') return node.value && /^(submit|button|reset)$/i.test(node.type) ? node.value : '';
    if (node.tagName === 'BR') return '\n';
    return textOf(node);
  };

  function flushRun(run, region) {
    if (!run.length) return;
    const els = run.filter(n => n.nodeType === 1 && (n.tagName === 'A' || n.tagName === 'BUTTON' || n.tagName === 'INPUT'));
    const total = clean(run.map(inlineText).join(''));
    if (!total) return;
    if (els.length === 1 && clean(inlineText(els[0])) === total) {
      push(classify(els[0], region) || 'p', total, region);
    } else {
      push('p', total, region);
    }
  }

  function walk(el, region) {
    if (el.nodeType !== 1) return;
    const tag = el.tagName;
    if (SKIP.has(tag)) return;
    if (!isVisible(el)) return;
    if (seenNodes.has(el)) return;
    seenNodes.add(el);
    region = regionOf(el, region);

    if (/^H[1-6]$/.test(tag)) { push(tag.toLowerCase(), textOf(el), region); return; }

    if (tag === 'A' || tag === 'BUTTON' || (tag === 'INPUT' && /^(submit|button|reset)$/i.test(el.type))) {
      if (tag === 'A' && el.querySelector(NESTED_BLOCK_SEL)) {
        // card-style link wrapping headings and paragraphs: descend into it
        for (const c of el.childNodes) {
          if (c.nodeType === 1) walk(c, region);
          else if (c.nodeType === 3) push('p', c.textContent, region);
        }
        return;
      }
      const t = tag === 'INPUT' ? el.value : (textOf(el) || el.getAttribute('aria-label') || el.title || (el.querySelector('img') && el.querySelector('img').alt) || '');
      push(classify(el, region) || 'link', t, region);
      return;
    }

    if (BLOCK_TEXT.has(tag) && !el.querySelector(NESTED_BLOCK_SEL)) {
      const t = textOf(el);
      const only = singleActionChild(el);
      let type = tag === 'LI' ? 'li' : 'p';
      if (only) type = classify(only, region) || type;
      push(type, t, region);
      return;
    }

    // Generic container: group consecutive inline nodes into one paragraph, recurse into blocks.
    let run = [];
    for (const c of el.childNodes) {
      if (c.nodeType === 3) { run.push(c); continue; }
      if (c.nodeType !== 1) continue;
      if (SKIP.has(c.tagName)) continue;
      if (!isVisible(c)) continue;
      const cs = getComputedStyle(c);
      const inlineLike = INLINE.has(c.tagName)
        && (cs.display === 'inline' || c.tagName === 'BR' || c.tagName === 'IMG' || c.tagName === 'INPUT')
        && !(c.tagName === 'A' && (c.querySelector(NESTED_BLOCK_SEL) || looksLikeButton(c)))
        && c.tagName !== 'BUTTON';
      if (inlineLike) { run.push(c); continue; }
      flushRun(run, region); run = [];
      walk(c, region);
    }
    flushRun(run, region);
  }

  walk(document.body, '');
  const dedup = [];
  for (const b of out) {
    const prev = dedup[dedup.length - 1];
    if (prev && prev.type === b.type && prev.text === b.text) continue;
    dedup.push(b);
  }
  return dedup;
}
"""

SCROLL_JS = r"""
async () => {
  const delay = (ms) => new Promise(r => setTimeout(r, ms));
  // defeat CSS smooth scrolling so every scrollTo is instant
  const style = document.createElement('style');
  style.textContent = 'html, body { scroll-behavior: auto !important; }';
  document.head.appendChild(style);
  const step = Math.max(300, window.innerHeight * 0.8);
  let y = 0, guard = 0;
  const maxH = () => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  while (y < maxH() && guard < 45) { y += step; window.scrollTo({ top: y, behavior: 'instant' }); await delay(50); guard++; }
  window.scrollTo({ top: 0, behavior: 'instant' });
  for (let i = 0; i < 20 && window.scrollY > 0; i++) { await delay(50); window.scrollTo({ top: 0, behavior: 'instant' }); }
  await delay(250);
  return maxH();
}
"""

# Full-page screenshots stretch the viewport to the page height, which makes position:fixed /
# sticky bars (headers, cookie banners, chat bubbles) float in odd places. Pin them where they sit.
PIN_FIXED_JS = r"""
() => {
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (cs.position === 'fixed') {
      // keep bottom-anchored overlays (cookie bars, chat bubbles) at the bottom of the first screen
      el.style.setProperty('position', 'absolute', 'important');
      el.style.setProperty('top', (r.top + window.scrollY) + 'px', 'important');
      el.style.setProperty('bottom', 'auto', 'important');
      if (cs.left !== 'auto') el.style.setProperty('left', r.left + 'px', 'important');
      if (cs.right !== 'auto' && cs.left === 'auto') el.style.setProperty('right', (window.innerWidth - r.right) + 'px', 'important');
    } else {
      el.style.setProperty('position', 'relative', 'important');
      el.style.setProperty('top', 'auto', 'important');
    }
    n++;
  }
  return n;
}
"""
