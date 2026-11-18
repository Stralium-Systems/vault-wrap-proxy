const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf8');

function renderHTML(language = 'en', overrides = {}) {
  const messages = {
    ...JSON.parse(fs.readFileSync(path.join(__dirname, '../app/static/locales/' + language + '.json'), 'utf8')),
    ...overrides,
  };
  const escaped = JSON.stringify(messages).replace(/[<>&]/g, char => ({'<': '\\u003c', '>': '\\u003e', '&': '\\u0026'}[char]));
  return html.replace(/__APP_(LANGUAGE|TITLE|TRANSLATIONS)__/g, (_, name) =>
    ({LANGUAGE: language, TITLE: messages.site_title, TRANSLATIONS: escaped}[name]));
}

async function openUI(config = { default_wrap_ttl_seconds: 30, max_wrap_ttl_seconds: 60 }, language = 'en', overrides = {}) {
  const dom = new JSDOM(renderHTML(language, overrides), {
    runScripts: 'dangerously',
    url: 'https://secrets.example.com',
    beforeParse(window) {
      window.fetch = async () => ({ ok: true, json: async () => ({language, ...config}) });
    },
  });
  await dom.window.eval('configurationReady');
  return dom;
}

test('JSON to fields preserves quoted secrets without creating attributes or handlers', async () => {
  const dom = await openUI();
  try {
    const key = 'quoted" key <&>';
    const value = '" onfocus="window.__probe=1" data-injected="yes <&> é中文';
    dom.window.document.getElementById('json-input').value = JSON.stringify({ [key]: value });
    dom.window.setInputMode('json');
    // setInputMode('json') copies the current fields, so set the imported JSON now.
    dom.window.document.getElementById('json-input').value = JSON.stringify({ [key]: value });
    dom.window.setInputMode('kv');
    const input = dom.window.document.querySelector('.kv-value');
    assert.equal(input.value, value);
    assert.equal(input.getAttribute('onfocus'), null);
    assert.equal(input.getAttribute('data-injected'), null);
    input.focus();
    assert.equal(dom.window.__probe, undefined);
    assert.deepEqual(JSON.parse(JSON.stringify(dom.window.getKvData())), { [key]: value });
  } finally {
    dom.window.close();
  }
});

test('prototype-like keys round-trip as ordinary JSON data', async () => {
  const dom = await openUI();
  try {
    const data = JSON.parse('{"__proto__":"secret","constructor":"value"}');
    dom.window.setKvData(data);
    assert.equal(JSON.stringify(dom.window.getKvData()), JSON.stringify(data));
  } finally {
    dom.window.close();
  }
});

test('UI uses the configured default and offers only valid TTLs', async () => {
  const dom = await openUI();
  try {
    const select = dom.window.document.getElementById('wrap-ttl');
    assert.equal(select.value, '30s');
    assert.equal(select.disabled, false);
    assert.equal(dom.window.document.getElementById('wrap-submit').disabled, false);
    assert.deepEqual([...select.options].map(option => option.value), ['30s', '60s']);
  } finally {
    dom.window.close();
  }
});

test('nonstandard valid defaults remain selectable', async () => {
  const dom = await openUI({ default_wrap_ttl_seconds: 37, max_wrap_ttl_seconds: 45 });
  try {
    assert.equal(dom.window.document.getElementById('wrap-ttl').value, '37s');
  } finally {
    dom.window.close();
  }
});

test('invalid public config leaves secret creation disabled', async () => {
  const dom = await openUI({ default_wrap_ttl_seconds: 100, max_wrap_ttl_seconds: 60 });
  try {
    assert.equal(dom.window.document.getElementById('wrap-submit').disabled, true);
    assert.match(dom.window.document.getElementById('wrap-result').textContent, /Unable to load/);
  } finally {
    dom.window.close();
  }
});

for (const [language, expected] of Object.entries({
  en: {tab: 'Protect', user: 'Username', unit: '1 hour', plural: '2 days', invalid: 'no longer valid', unavailable: 'temporarily unavailable'},
  fr: {tab: 'Protéger', user: 'Identifiant', unit: '1 heure', plural: '2 jours', invalid: "n'est plus valide", unavailable: 'temporairement indisponible'},
  es: {tab: 'Proteger', user: 'Usuario', unit: '1 hora', plural: '2 días', invalid: 'ya no es válido', unavailable: 'no está disponible temporalmente'},
})) {
  test(language + ': static and dynamic UI text, dates, units and errors are localized', async () => {
    const dom = await openUI(undefined, language);
    try {
      const {document} = dom.window;
      assert.equal(document.documentElement.lang, language);
      assert.ok(document.querySelector('[data-tab="wrap"]').textContent.includes(expected.tab));
      assert.equal(document.querySelector('.kv-key').value, expected.user);
      assert.equal(dom.window.formatDuration(3600), expected.unit);
      assert.equal(dom.window.formatDuration(172800), expected.plural);
      assert.equal(dom.window.formatDate('2026-11-18T12:00:00Z'), new Intl.DateTimeFormat(language, {dateStyle: 'medium', timeStyle: 'medium'}).format(new Date('2026-11-18T12:00:00Z')));
      dom.window.addField();
      const input = [...document.querySelectorAll('.kv-key')].at(-1);
      const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../app/static/locales/' + language + '.json'), 'utf8'));
      assert.equal(input.placeholder, catalog.field_name);
      const footer = document.querySelector('.site-footer');
      assert.ok(footer.textContent.includes('Stralium Systems'));
      assert.equal(footer.querySelector('[data-i18n="footer_website"]').textContent, catalog.footer_website);
      const links = [...footer.querySelectorAll('a')];
      assert.deepEqual(links.map(link => link.href), ['https://stralium-system.fr/', 'https://github.com/Stralium-Systems/vault-wrap-proxy']);
      for (const link of links) {
        assert.equal(link.target, '_blank');
        assert.ok(link.relList.contains('noopener'));
        assert.ok(link.relList.contains('noreferrer'));
      }
      assert.equal(links[1].title, catalog.footer_source_title);
      document.querySelector('[data-tab="unwrap"] span').click();
      assert.equal(document.querySelector('[data-tab="unwrap"]').classList.contains('active'), true);
      document.getElementById('unwrap-token').value = 'synthetic';
      dom.window.fetch = async () => ({ok: false, status: 400, json: async () => ({detail: 'machine message without French substrings'})});
      await dom.window.unwrapToken();
      assert.ok(document.getElementById('unwrap-result').textContent.includes(expected.invalid));
      document.getElementById('lookup-token').value = 'synthetic';
      dom.window.fetch = async () => ({ok: false, status: 503, json: async () => ({detail: catalog.err_vault_unavailable})});
      await dom.window.lookupToken();
      assert.ok(document.getElementById('lookup-result').textContent.includes(expected.unavailable));
      dom.window.fetch = async () => { throw new TypeError('English browser network message'); };
      await dom.window.unwrapToken();
      assert.equal(document.getElementById('unwrap-result').textContent, catalog.network_error);
    } finally { dom.window.close(); }
  });

  test(language + ': translations never change or execute user data', async () => {
    const dom = await openUI(undefined, language);
    try {
      const original = {'original " <key>': 'contraseña é中文 " onfocus="window.injected=1', '__proto__value': 'Identifiant'};
      dom.window.setKvData(original);
      assert.deepEqual(JSON.parse(JSON.stringify(dom.window.getKvData())), original);
      const node = dom.window.document.querySelector('.kv-value');
      assert.equal(node.getAttribute('onfocus'), null);
      node.focus();
      assert.equal(dom.window.injected, undefined);
      let sent;
      dom.window.fetch = async (_, options) => {
        sent = JSON.parse(options.body);
        return {ok: true, json: async () => ({token: 'synthetic-code', ttl: 30})};
      };
      await dom.window.wrapData();
      assert.deepEqual(sent.data, original);
      assert.equal(sent.ttl, '30s');
      dom.window.renderUnwrapResult(original);
      assert.equal(dom.window.document.querySelector('.revealed-value').textContent, Object.values(original)[0]);
      assert.equal(dom.window.document.querySelector('#unwrap-result [onfocus]'), null);
    } finally { dom.window.close(); }
  });
}

test('translation strings are data and cannot create executable markup', async () => {
  const marker = '<img src=x onerror="window.injected=1"></script><script>window.injected=1</script>';
  const dom = await openUI(undefined, 'en', {wrap_intro: marker});
  try {
    assert.equal(dom.window.injected, undefined);
    assert.equal(dom.window.document.querySelector('[data-i18n="wrap_intro"]').textContent, marker);
    assert.equal(dom.window.document.querySelector('[data-i18n="wrap_intro"] img'), null);
  } finally { dom.window.close(); }
});

test('configuration language mismatch fails safely', async () => {
  const dom = await openUI({language: 'es', default_wrap_ttl_seconds: 30, max_wrap_ttl_seconds: 60}, 'en');
  try {
    assert.equal(dom.window.document.getElementById('wrap-submit').disabled, true);
    assert.equal(dom.window.document.getElementById('wrap-result').classList.contains('hidden'), false);
  } finally { dom.window.close(); }
});
