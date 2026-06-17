const form = document.querySelector("#question-form");
const input = document.querySelector("#question-input");
const answer = document.querySelector("#answer");
const sqlBox = document.querySelector("#sql");
const confidence = document.querySelector("#confidence");
const resultsTable = document.querySelector("#results-table");
const rowCount = document.querySelector("#row-count");
const chart = document.querySelector("#chart");
const samples = document.querySelector("#samples");
const schema = document.querySelector("#schema");
const statusBadge = document.querySelector("#status");
const tablePreview = document.querySelector("#table-preview");
const apiDocs = document.querySelector("#api-docs");

function setLoading(isLoading) {
  form.querySelector("button").disabled = isLoading;
  statusBadge.textContent = isLoading ? "Running query..." : statusBadge.dataset.readyText || "Ready";
}

function renderRows(rows) {
  rowCount.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  resultsTable.innerHTML = "";
  renderChart(rows);

  if (!rows.length) {
    resultsTable.innerHTML = "<tbody><tr><td>No rows to show</td></tr></tbody>";
    return;
  }

  const columns = Object.keys(rows[0]);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.replaceAll("_", " ");
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      td.textContent = row[column] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  resultsTable.append(thead, tbody);
}

function renderChart(rows) {
  chart.innerHTML = "";
  if (!rows.length) {
    return;
  }

  const columns = Object.keys(rows[0]);
  const labelColumn = columns.find((column) => typeof rows[0][column] === "string") || columns[0];
  const valueColumn = columns.find((column) => column !== labelColumn && typeof rows[0][column] === "number");
  if (!valueColumn) {
    return;
  }

  const chartRows = rows.slice(0, 8);
  const maxValue = Math.max(...chartRows.map((row) => Number(row[valueColumn]) || 0));
  if (!maxValue) {
    return;
  }

  chartRows.forEach((row) => {
    const value = Number(row[valueColumn]) || 0;
    const bar = document.createElement("div");
    bar.className = "bar-row";
    bar.innerHTML = `
      <div class="bar-label" title="${row[labelColumn]}">${row[labelColumn]}</div>
      <div class="bar-track"><div class="bar-fill" style="width: ${(value / maxValue) * 100}%"></div></div>
      <div class="bar-value">${value.toLocaleString()}</div>
    `;
    chart.appendChild(bar);
  });
}

async function askQuestion(question) {
  setLoading(true);
  answer.classList.remove("error");
  answer.textContent = "Thinking through the movie data...";

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "The question could not be answered.");
    }

    answer.textContent = data.answer;
    sqlBox.textContent = data.sql;
    confidence.textContent = `${Math.round(data.confidence * 100)}% confidence`;
    renderRows(data.rows);
  } catch (error) {
    answer.textContent = error.message;
    answer.classList.add("error");
    sqlBox.textContent = "No SQL generated.";
    confidence.textContent = "Needs a clearer question";
    renderRows([]);
  } finally {
    setLoading(false);
  }
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    const text = data.llm_enabled ? `OpenAI ${data.model}` : "Demo mode";
    statusBadge.textContent = text;
    statusBadge.dataset.readyText = text;
  } catch {
    statusBadge.textContent = "Ready";
    statusBadge.dataset.readyText = "Ready";
  }
}

async function loadSamples() {
  const response = await fetch("/api/sample-questions");
  const data = await response.json();
  samples.innerHTML = "";
  data.questions.forEach((question) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sample";
    button.textContent = question;
    button.addEventListener("click", () => {
      input.value = question;
      askQuestion(question);
    });
    samples.appendChild(button);
  });
}

async function loadSchema() {
  try {
    const response = await fetch("/api/schema");
    const data = await response.json();
    schema.innerHTML = "";

    Object.entries(data.tables).forEach(([tableName, columns]) => {
      const block = document.createElement("div");
      block.className = "table-schema";
      const title = document.createElement("h3");
      title.textContent = tableName;
      block.appendChild(title);

      columns.forEach((column) => {
        const row = document.createElement("div");
        row.className = "column";
        row.innerHTML = `<span>${column.name}</span><span>${column.type}</span>`;
        block.appendChild(row);
      });
      schema.appendChild(block);
    });
  } catch (error) {
    schema.innerHTML = `<p class="error">${error.message}</p>`;
  }
}

function buildMiniTable(rows) {
  if (!rows.length) {
    return "<p>No rows in this table.</p>";
  }

  const columns = Object.keys(rows[0]);
  const headers = columns.map((column) => `<th>${column.replaceAll("_", " ")}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((column) => `<td>${row[column] ?? ""}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  return `
    <div class="table-wrap mini-table-wrap">
      <table>
        <thead><tr>${headers}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

async function loadTablePreview() {
  try {
    const response = await fetch("/api/table-preview?limit=6");
    const data = await response.json();
    tablePreview.innerHTML = "";

    Object.entries(data.tables).forEach(([tableName, preview]) => {
      const section = document.createElement("section");
      section.className = "table-preview";
      section.innerHTML = `
        <div class="section-title">
          <h3>${tableName}</h3>
          <span>${preview.count.toLocaleString()} rows</span>
        </div>
        ${buildMiniTable(preview.rows)}
      `;
      tablePreview.appendChild(section);
    });
  } catch (error) {
    tablePreview.innerHTML = `<p class="error">${error.message}</p>`;
  }
}

async function loadApiDocs() {
  try {
    const response = await fetch("/api/docs");
    const data = await response.json();
    apiDocs.innerHTML = "";

    data.endpoints.forEach((endpoint) => {
      const block = document.createElement("section");
      block.className = "endpoint";
      block.innerHTML = `
        <div class="endpoint-route">
          <span class="method">${endpoint.method}</span>
          <code>${endpoint.path}</code>
        </div>
        <p>${endpoint.purpose}</p>
        <dl>
          <dt>Request</dt>
          <dd>${endpoint.request}</dd>
          <dt>Response</dt>
          <dd>${endpoint.response}</dd>
        </dl>
      `;
      apiDocs.appendChild(block);
    });
  } catch (error) {
    apiDocs.innerHTML = `<p class="error">${error.message}</p>`;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (question) {
    askQuestion(question);
  }
});

loadStatus();
loadSamples();
loadSchema();
loadTablePreview();
loadApiDocs();
