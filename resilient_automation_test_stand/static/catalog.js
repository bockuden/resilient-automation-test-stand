const configNode = document.querySelector('#catalog-config');
const config = JSON.parse(configNode.textContent);
const catalog = document.querySelector('#catalog');
const status = document.querySelector('#status');
const nav = document.querySelector('nav');

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
      outer.dataset.testid = 'catalog-item';
      outer.dataset.itemId = item.id;
      outer.innerHTML =
        config.scenario === 'dom-change'
          ? `<div class="content"><span data-testid="item-name">${item.name}</span><strong data-testid="item-price">${item.price.toFixed(2)}</strong></div>`
          : `<h2 data-testid="item-name">${item.name}</h2><span data-testid="item-price">${item.price.toFixed(2)}</span>`;
      fragment.appendChild(outer);
    }

    catalog.appendChild(fragment);
    status.textContent = `Page ${data.page} loaded on attempt ${data.attempt}`;
    status.dataset.state = 'success';

    if (data.page < data.total_pages) {
      const next = document.createElement('button');
      next.type = 'button';
      next.dataset.testid = 'next-page';
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
