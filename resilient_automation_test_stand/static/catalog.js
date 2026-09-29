const configNode = document.querySelector('#catalog-config');
const config = JSON.parse(configNode.textContent);
const catalog = document.querySelector('#catalog');
const status = document.querySelector('#status');
const nav = document.querySelector('nav');
catalog.dataset.testid = config.selectors.catalog;

async function loadPage(page) {
  status.textContent = `Loading page ${page}...`;
  status.dataset.state = 'loading';
  catalog.replaceChildren();
  nav.replaceChildren();
  const query = new URLSearchParams({
    page,
    scenario: config.scenario,
    run_id: config.runId,
    fail_for: config.failFor,
    delay_ms: config.delayMs,
    failure_delay_ms: config.failureDelayMs,
    fail_page: config.failPage,
    total_pages: config.totalPages,
  });

  try {
    const response = await fetch(`/api/catalog?${query}`);
    if (!response.ok) {
      const retryAfter = response.headers.get('Retry-After');
      throw new Error(`HTTP ${response.status}${retryAfter ? `; retry-after=${retryAfter}` : ''}`);
    }
    const data = await response.json();
    const fragment = document.createDocumentFragment();

    for (const item of data.items) {
      const outer = document.createElement(config.scenario === 'dom-change' ? 'article' : 'div');
      outer.className = config.scenario === 'dom-change' ? 'result-tile-v2' : 'product-card';
      outer.dataset.testid = config.selectors.item;
      outer.dataset.itemId = item.id;
      const content = config.scenario === 'dom-change' ? document.createElement('div') : outer;
      if (config.scenario === 'dom-change') content.className = 'content';
      const name = document.createElement(config.scenario === 'dom-change' ? 'span' : 'h2');
      name.className = 'item-name';
      name.dataset.testid = config.selectors.item_name;
      name.textContent = item.name;
      const price = document.createElement(config.scenario === 'dom-change' ? 'strong' : 'span');
      price.className = 'item-price';
      price.dataset.testid = config.selectors.item_price;
      price.textContent = item.price.toFixed(2);
      content.append(name, price);
      if (content !== outer) outer.appendChild(content);
      fragment.appendChild(outer);
    }

    catalog.appendChild(fragment);
    status.textContent = `Page ${data.page} loaded on attempt ${data.attempt}`;
    status.dataset.state = 'success';

    if (data.page < data.total_pages) {
      const next = document.createElement('button');
      next.type = 'button';
      next.dataset.testid = config.selectors.next_page;
      next.textContent = 'Next page';
      next.addEventListener('click', () => loadPage(data.page + 1));
      nav.appendChild(next);
    }
  } catch (error) {
    status.textContent = `Catalog error: ${error.message}`;
    status.dataset.testid = 'catalog-error';
    status.dataset.state = 'error';
  }
}

loadPage(1);
