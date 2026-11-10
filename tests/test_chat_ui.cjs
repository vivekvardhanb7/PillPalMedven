const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test } = require('node:test');
const { runInNewContext } = require('node:vm');
const { randomUUID } = require('node:crypto');

test('typing the next message preserves the pending reply', async () => {
  const elements = new Map();
  const document = {};
  function $(selector) {
    if (selector === document) return { ready: callback => callback() };
    if (!elements.has(selector)) {
      const element = {
        handlers: {}, value: selector === '#language' ? 'en' : '', textValue: '',
        children: [], 0: { scrollHeight: 0 },
        on(event, callback) { this.handlers[event] = callback; return this; },
        prop() { return this; }, attr() { return this; },
        addClass() { return this; }, removeClass() { return this; },
        remove() { return this; }, scrollTop() { return this; },
        trigger() { return this; },
        text(value) { this.textValue = value; return this; },
        val(value) { if (value === undefined) return this.value; this.value = value; return this; },
        append(child) { this.children.push(child); return this; },
        appendTo(parent) { parent.append(this); return this; },
      };
      // Newly created DOM elements must have separate identities.
      if (selector.startsWith('<')) return element;
      elements.set(selector, element);
    }
    return elements.get(selector);
  }
  let chatSignal;
  let finishChat;
  const fetch = async (url, options) => {
    if (url === '/api/sessions') {
      return { ok: true, json: async () => ({
        session_id: 'session', access_token: 'token', session_revision: 0,
      }) };
    }
    assert.equal(url, '/api/chat');
    chatSignal = options.signal;
    return new Promise(resolve => { finishChat = resolve; });
  };
  const html = readFileSync(resolve(__dirname, '../templates/chat.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace('{{ voice_enabled | tojson }}', 'false');
  runInNewContext(script, { $, document, fetch, AbortController, crypto: { randomUUID } });
  const flush = () => new Promise(resolve => setImmediate(resolve));
  await flush();
  $('#text').val('hello');
  $('#messageArea').handlers.submit({ preventDefault() {} });
  assert.ok(chatSignal);
  $('#text').val('my next question');
  $('#text').handlers.input();
  assert.equal(chatSignal.aborted, false);
  finishChat({ ok: true, status: 200, json: async () => ({
    message: 'Hello!', session_revision: 1, response_id: 'reply', language: 'en',
    sources: [{ title: 'Medical_book.pdf', source_id: 'BOOK-123' }],
  }) });
  await flush();
  assert.equal($('#messageFormeight').children.length, 2);
  const replyBubble = $('#messageFormeight').children[1].children[0];
  assert.equal(replyBubble.children[0].textValue, 'Hello!');
  assert.equal(replyBubble.children[1].textValue, 'Sources: Medical_book.pdf [BOOK-123]');
  assert.equal($('#text').val(), 'my next question');
});
