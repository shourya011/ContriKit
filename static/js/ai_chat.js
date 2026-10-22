/* ContribKit — AI Contribution Assistant widget.
 *
 * Talks only to the same-origin POST /ai/chat/ endpoint (CSP connect-src
 * 'self'). Never contacts an LLM provider directly; no keys in this file.
 * All LLM output is rendered with textContent — never innerHTML.
 */

document.addEventListener('DOMContentLoaded', initAiChat);

function initAiChat() {
  const root = document.getElementById('aiChat');
  if (!root) return;

  const fab = document.getElementById('aiChatFab');
  const panel = document.getElementById('aiChatPanel');
  const closeBtn = document.getElementById('aiChatClose');
  const body = document.getElementById('aiChatBody');
  const messages = document.getElementById('aiChatMessages');
  const empty = document.getElementById('aiChatEmpty');
  const gate = document.getElementById('aiChatGate');
  const suggestions = document.getElementById('aiChatSuggestions');
  const form = document.getElementById('aiChatForm');
  const input = document.getElementById('aiChatInput');
  const sendBtn = document.getElementById('aiChatSend');

  const authenticated = root.dataset.authenticated === 'true';
  const loginUrl = root.dataset.loginUrl || '/accounts/login/';
  /* Server-side page context: the chat POST always targets /ai/chat/, so the
     browser's own path is sent along. The backend rejects anything that is
     not a same-origin absolute path. */
  const pagePath = window.location.pathname || '/';
  /* Slightly longer than the server's 55s request budget. */
  const REQUEST_TIMEOUT_MS = 70000;
  let busy = false;
  let lastMessage = '';

  /* ── CSRF ──
     base.html publishes the token as <meta name="csrf-token">; the cookie is
     the fallback. Django rejects a POST without it (403 "CSRF cookie not
     set"), so this must resolve to a real token before we send anything. */
  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const fromMeta = meta && meta.getAttribute('content');
    if (fromMeta) return fromMeta;
    return typeof getCookie === 'function' ? getCookie('csrftoken') : null;
  }

  /* ── Open / close ── */
  function openPanel() {
    panel.hidden = false;
    // Force reflow so the transition plays.
    void panel.offsetWidth;
    panel.classList.add('is-open');
    fab.setAttribute('aria-expanded', 'true');
    if (authenticated) {
      input.focus();
    }
  }

  function closePanel() {
    panel.classList.remove('is-open');
    fab.setAttribute('aria-expanded', 'false');
    fab.focus();
    panel.addEventListener('transitionend', () => {
      if (!panel.classList.contains('is-open')) panel.hidden = true;
    }, { once: true });
  }

  fab.addEventListener('click', () => {
    if (panel.classList.contains('is-open')) closePanel();
    else openPanel();
  });

  closeBtn.addEventListener('click', closePanel);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains('is-open')) closePanel();
  });

  /* ── Guest gate vs. enabled form ── */
  if (authenticated) {
    form.classList.add('is-enabled');
    suggestions.hidden = false;
  } else {
    gate.hidden = false;
    suggestions.hidden = true;
    form.classList.remove('is-enabled');
  }

  /* ── Suggestions ── */
  suggestions.querySelectorAll('.ai-chat__chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      input.value = chip.dataset.suggestion || '';
      submitMessage();
    });
  });

  /* ── Input helpers ── */
  function autoResize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  }
  input.addEventListener('input', autoResize);

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitMessage();
    }
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitMessage();
  });

  async function submitMessage() {
    const text = input.value.trim();
    if (!text || busy) return;

    if (!authenticated) {
      window.location.href = loginUrl;
      return;
    }

    // Resolve the token *before* touching the busy state: an early return
    // after locking the input would leave the form disabled forever.
    const token = csrfToken();
    if (!token) {
      hideEmptyState();
      appendMessage(
        'error',
        'I could not read your security token. Please reload the page and try again.'
      );
      return;
    }

    busy = true;
    lastMessage = text;
    input.disabled = true;
    sendBtn.disabled = true;
    messages.setAttribute('aria-busy', 'true');
    hideEmptyState();
    const userMessage = appendMessage('user', text);
    input.value = '';
    autoResize();
    showTyping();

    // A failed turn is not stored in session history, so remove the local echo
    // too; otherwise retrying would show the same question twice.
    function fail(message) {
      if (userMessage.isConnected) userMessage.remove();
      restoreInput(text);
      appendMessage('error', message);
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch('/ai/chat/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': token,
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ message: text, page: pagePath }),
        signal: controller.signal,
      });

      let data = {};
      try { data = await response.json(); } catch (_) { /* non-JSON body */ }

      removeTyping();

      if (!response.ok) {
        if (response.status === 403 && data.error === 'login_required') {
          window.location.href = loginUrl;
          return;
        }
        if (response.status === 403) {
          fail('Your security token expired. Reload the page and try again.');
          return;
        }
        fail(errorMessage(data, response.status));
        return;
      }

      if (!data.reply || !String(data.reply).trim()) {
        fail('The assistant returned an empty answer. Please try again.');
        return;
      }

      lastMessage = '';
      const assistantEl = appendMessage('assistant', data.reply);
      renderSources(assistantEl, data.sources || []);
    } catch (err) {
      removeTyping();
      if (err && err.name === 'AbortError') {
        fail('The assistant took too long to answer. Please try again in a moment.');
      } else {
        fail('Could not reach the assistant. Check your connection and try again.');
      }
    } finally {
      window.clearTimeout(timeoutId);
      busy = false;
      input.disabled = false;
      sendBtn.disabled = false;
      messages.setAttribute('aria-busy', 'false');
      input.focus();
    }
  }

  function errorMessage(data, status) {
    if (data && data.error) return data.error;
    if (status === 429) return 'The assistant is busy. Please wait a moment and try again.';
    if (status >= 500) return 'The assistant is temporarily unavailable. Please try again shortly.';
    return 'Something went wrong. Please try again.';
  }

  function restoreInput(text) {
    if (!input.value) {
      input.value = text || lastMessage || '';
      autoResize();
    }
  }

  /* ── Rendering (safe: textContent only) ── */
  function hideEmptyState() {
    if (empty) empty.hidden = true;
  }

  function appendMessage(role, text) {
    hideEmptyState();
    const wrap = document.createElement('div');
    wrap.className = 'ai-chat__msg ai-chat__msg--' + (role === 'user' ? 'user' : role === 'error' ? 'error' : 'assistant');

    const bubble = document.createElement('div');
    bubble.className = 'ai-chat__bubble';
    renderSafeContent(bubble, text);

    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function renderSafeContent(container, text) {
    const parts = splitFences(text || '');
    for (const part of parts) {
      if (part.isCode) {
        const pre = document.createElement('pre');
        pre.className = 'ai-chat__code';
        const code = document.createElement('code');
        code.textContent = part.text;
        pre.appendChild(code);
        container.appendChild(pre);
      } else if (part.text) {
        const div = document.createElement('div');
        div.textContent = part.text;
        container.appendChild(div);
      }
    }
  }

  function splitFences(text) {
    const parts = [];
    const regex = /(```|~~~)([\s\S]*?)\1/g;
    let last = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > last) parts.push({ text: text.slice(last, match.index), isCode: false });
      parts.push({ text: match[2], isCode: true });
      last = regex.lastIndex;
    }
    if (last < text.length) parts.push({ text: text.slice(last), isCode: false });
    return parts.length ? parts : [{ text, isCode: false }];
  }

  function renderSources(assistantElement, sources) {
    if (!sources.length) return;
    const icons = {
      issue: 'bi-bug-fill',
      template: 'bi-file-earmark-code-fill',
      cheatsheet: 'bi-terminal-fill',
      github: 'bi-github',
    };
    const row = document.createElement('div');
    row.className = 'ai-chat__sources';
    sources.forEach((source) => {
      const href = safeHref(source.url);
      if (!href) return;
      const link = document.createElement('a');
      link.className = 'ai-chat__source';
      link.href = href;
      link.textContent = source.label || href;
      if (source.type === 'github') {
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
      const icon = document.createElement('i');
      icon.className = 'bi ' + (icons[source.type] || 'bi-link-45deg');
      icon.setAttribute('aria-hidden', 'true');
      link.prepend(icon);
      row.appendChild(link);
    });
    if (!row.children.length) return;
    assistantElement.appendChild(row);
    scrollToBottom();
  }

  /* Only same-origin paths and http(s) URLs may become links. */
  function safeHref(url) {
    if (typeof url !== 'string' || !url) return null;
    if (url.startsWith('/') && !url.startsWith('//')) return url;
    try {
      const parsed = new URL(url, window.location.origin);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.href;
      }
    } catch (_) { /* invalid URL */ }
    return null;
  }

  function showTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'ai-chat__msg ai-chat__msg--assistant';
    wrap.id = 'aiChatTyping';
    const bubble = document.createElement('div');
    bubble.className = 'ai-chat__bubble ai-chat__typing';
    for (let i = 0; i < 3; i++) bubble.appendChild(document.createElement('i'));
    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    scrollToBottom();
  }

  function removeTyping() {
    const typing = document.getElementById('aiChatTyping');
    if (typing) typing.remove();
  }

  function scrollToBottom() {
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  }
}
