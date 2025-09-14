async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function refreshAll() {
  try {
    const status = await api('/status');
    document.getElementById('status-line').textContent = `Scheduler: ${status.scheduler_running ? 'running' : 'stopped'} | Next: ${status.next_run_time || '—'}`;

    const inv = await api('/inventory');
    const invEl = document.getElementById('inventory');
    invEl.innerHTML = '';
    for (const [k, v] of Object.entries(inv)) {
      const div = document.createElement('div');
      div.className = 'inv-item';
      div.innerHTML = `<strong>${k}</strong>: stock=${v.stock} pending=${v.restock_pending || 0} eta=${v.restock_eta || '-'} `;
      invEl.appendChild(div);
    }

    const prices = await api('/prices');
    const pEl = document.getElementById('prices');
    pEl.innerHTML = '';
    for (const [k, v] of Object.entries(prices)) {
      const row = document.createElement('div');
      row.className = 'price-item';

      const label = document.createElement('span');
      label.textContent = k;

      const input = document.createElement('input');
      input.type = 'number';
      input.min = '0';
      input.step = '0.01';
      input.value = Number(v).toFixed(2);

      const btn = document.createElement('button');
      btn.textContent = 'Update';
      btn.addEventListener('click', async () => {
        try {
          btn.disabled = true;
          await api('/prices', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item: k, sell_price: parseFloat(input.value) })
          });
          btn.textContent = 'Saved';
          setTimeout(() => { btn.textContent = 'Update'; btn.disabled = false; }, 1000);
        } catch (e) {
          console.error(e);
          btn.textContent = 'Error';
          btn.disabled = false;
        }
      });

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') btn.click();
      });

      row.appendChild(label);
      row.appendChild(input);
      row.appendChild(btn);
      pEl.appendChild(row);
    }

    const sales = await api('/sales/today');
    const sEl = document.getElementById('sales');
    sEl.innerHTML = '';
    if (!sales.sales || sales.sales.length === 0) {
      sEl.textContent = 'No sales for today';
    } else {
      for (const s of sales.sales) {
        const r = document.createElement('div');
        r.textContent = `${s.product} x${s.qty} @ $${s.price.toFixed(2)}`;
        sEl.appendChild(r);
      }
    }

    const fin = await api('/financials/daily');
    const fEl = document.getElementById('financials');
    fEl.innerHTML = '';
    if (fin.financials) {
      fEl.innerHTML = `<div>Profit: $${Number(fin.financials.profit).toFixed(2)}</div>`;
    } else {
      fEl.textContent = 'No financials available';
    }
  } catch (err) {
    console.error(err);
    document.getElementById('status-line').textContent = 'Error fetching data';
  }
}

document.getElementById('refresh').addEventListener('click', refreshAll);

document.getElementById('simulate-day').addEventListener('click', async () => {
  try {
    document.getElementById('status-line').textContent = 'Simulating...';
    await api('/simulate/day', { method: 'POST' });
    await refreshAll();
  } catch (e) { console.error(e); document.getElementById('status-line').textContent = 'Simulate failed'; }
});

document.getElementById('apply-restock').addEventListener('click', async () => {
  try {
    document.getElementById('status-line').textContent = 'Applying restocks...';
    await api('/inventory/restock', { method: 'POST' });
    await refreshAll();
  } catch (e) { console.error(e); document.getElementById('status-line').textContent = 'Restock failed'; }
});

document.getElementById('reset-simulation').addEventListener('click', async () => {
  try {
    if (!confirm('Reset simulation data to defaults? This will erase sales and financials. Continue?')) return;
    document.getElementById('status-line').textContent = 'Resetting simulation...';
    await api('/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reset_config: true }) });
    await refreshAll();
    document.getElementById('status-line').textContent = 'Reset complete';
  } catch (e) { console.error(e); document.getElementById('status-line').textContent = 'Reset failed'; }
});

// initial load
refreshAll();

// --- Sales trends charting ---
let salesChart = null;
let salesDataCache = null;

async function ensureChartLib() {
  if (window.Chart) return;
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function aggregateSalesByDate(sales) {
  // sales is array of {date, product, qty, price}
  const byDate = {}; // date -> {total, perProduct: {p: qty}}
  const products = new Set();
  for (const s of sales) {
    const d = (s.date || s.sale_date || s.timestamp || '').slice(0, 10) || s.date;
    if (!d) continue;
    products.add(s.product || s.item || s.product_name || 'Unknown');
    const prod = s.product || s.item || s.product_name || 'Unknown';
    byDate[d] = byDate[d] || { total: 0, perProduct: {} };
    byDate[d].total += Number(s.qty || 0);
    byDate[d].perProduct[prod] = (byDate[d].perProduct[prod] || 0) + Number(s.qty || 0);
  }
  const dates = Object.keys(byDate).sort();
  return { dates, byDate, products: Array.from(products).sort() };
}

async function loadAndRenderSalesChart() {
  await ensureChartLib();
  try {
    const res = await api('/sales/history');
    const sales = res.sales || res.sales || [];
    salesDataCache = sales;
    const agg = aggregateSalesByDate(sales);

    const select = document.getElementById('product-select');
    select.innerHTML = '<option value="__all__">All products</option>' + agg.products.map(p => `<option value="${p}">${p}</option>`).join('');

    const ctx = document.getElementById('sales-trend').getContext('2d');
    const labels = agg.dates;
    const totalData = labels.map(d => agg.byDate[d].total || 0);

    // Normalize/scale Y axis when values are large to improve visibility
    const maxVal = Math.max(...totalData, 0);
    let scaleLabel = '';
    let scaledTotal = totalData;
    if (maxVal > 50) {
      // if very large, scale to 'per 10' to compress the chart
      scaledTotal = totalData.map(v => (v / 10));
      scaleLabel = ' (qty / 10)';
    }

    const datasets = [{ label: 'Total qty' + scaleLabel, data: scaledTotal, borderColor: '#007bff', backgroundColor: 'rgba(0,123,255,0.1)', tension: 0.2 }];

    if (salesChart) salesChart.destroy();
    salesChart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2,
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              label: function(context) {
                const idx = context.dataIndex;
                const d = labels[idx];
                const raw = agg.byDate[d].total || 0;
                if (scaleLabel) {
                  return `${context.dataset.label}: ${context.parsed.y} (raw ${raw})`;
                }
                return `${context.dataset.label}: ${raw}`;
              }
            }
          }
        }
      }
    });

    select.addEventListener('change', () => {
      const prod = select.value;
      const rawData = labels.map(d => {
        if (prod === '__all__') return agg.byDate[d].total || 0;
        return agg.byDate[d].perProduct[prod] || 0;
      });
      // scale if needed
      const rawMax = Math.max(...rawData, 0);
      let scaled = rawData;
      let sLabel = '';
      if (rawMax > 50) { scaled = rawData.map(v => v / 10); sLabel = ' (qty / 10)'; }
      salesChart.data.datasets = [{ label: (prod === '__all__' ? 'Total qty' : prod) + sLabel, data: scaled, borderColor: '#28a745', backgroundColor: 'rgba(40,167,69,0.1)', tension: 0.2 }];
      salesChart.update();
    });

  } catch (e) {
    console.error('Failed to load sales history for chart', e);
  }
}

// render chart after initial data fetch
loadAndRenderSalesChart();
