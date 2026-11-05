/**
 * Web-based Administrative Pseudo-Terminal Script
 * Provides an interactive CLI console on Port 5002 for executing raw SQL statements
 * and generating dynamic tabular reports outside the terminal.
 */

document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('terminal-input');
    const output = document.getElementById('terminal-output');
    const form = document.getElementById('terminal-form');
    const presetSelect = document.getElementById('preset-select');

    const reportSection = document.getElementById('report-section');
    const reportQueryText = document.getElementById('report-query-text');
    const reportMetaCount = document.getElementById('report-meta-count');
    const reportMetaTime = document.getElementById('report-meta-time');
    const reportTableHead = document.getElementById('report-table-head');
    const reportTableBody = document.getElementById('report-table-body');

    if (!input || !output || !form) return;

    /**
     * Auto-resize the terminal textarea to fit content between min and max heights.
     * @param {HTMLTextAreaElement} el - The textarea DOM element.
     */
    function autoResizeTerminalTextarea(el) {
        if (!el) return;
        el.style.height = 'auto';
        const targetHeight = Math.min(Math.max(el.scrollHeight, 46), 160);
        el.style.height = `${targetHeight}px`;
    }
    window.autoResizeTerminalTextarea = autoResizeTerminalTextarea;

    // Command history navigation
    const history = [];
    let historyIndex = -1;

    // Dropdown change listener to instantly populate terminal input
    if (presetSelect) {
        presetSelect.addEventListener('change', () => {
            if (presetSelect.value) {
                input.value = presetSelect.value;
                autoResizeTerminalTextarea(input);
                input.focus();
            }
        });
    }

    // Dynamic auto-resize while typing
    input.addEventListener('input', () => {
        autoResizeTerminalTextarea(input);
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        let cmd = input.value.trim();
        if (!cmd && history.length > 0) {
            cmd = history[history.length - 1];
        }

        if (!cmd) {
            appendOutput('Please enter a SQL query or select a preset to generate report.', 'text-amber-400');
            return;
        }

        // Add to history
        history.push(cmd);
        historyIndex = history.length;

        // Echo command to terminal
        appendOutput(`$ ${escapeHtml(cmd)}`, 'text-blue-400 font-semibold');

        if (cmd.toLowerCase() === 'clear') {
            output.innerHTML = '';
            input.value = '';
            return;
        }

        if (cmd.toLowerCase() === 'help') {
            appendOutput(
                "Available administrative console commands:\n" +
                "  SELECT ...                Execute queries & generate external tabular report\n" +
                "  EXPLAIN ...               Inspect query planner execution plan\n" +
                "  SHOW ...                  Inspect PostgreSQL system configuration\n" +
                "  \\dt                       List all relations in public schema\n" +
                "  \\dv                       List all database views\n" +
                "  clear                     Clear the console output log\n" +
                "  help                      Display this help menu",
                'text-zinc-400'
            );
            input.value = '';
            return;
        }

        // Execute via backend API and generate report
        try {
            const res = await fetch('/api/terminal/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: cmd })
            });
            const data = await res.json();

            if (!res.ok) {
                appendOutput(`ERROR: ${data.error || 'Execution failed'}`, 'text-rose-400');
            } else if (data.columns && data.rows) {
                renderExternalReport(cmd, data.columns, data.rows, data.execution_time);
                appendOutput(`✓ Tabular report generated (${data.rows.length} rows, ${data.execution_time}ms). Rendered below terminal.`, 'text-emerald-400');
            } else if (data.message) {
                appendOutput(data.message, 'text-emerald-400');
            }
        } catch (err) {
            appendOutput(`NETWORK ERROR: ${err.message}`, 'text-rose-500');
        }

        output.scrollTop = output.scrollHeight;
    });

    function renderExternalReport(query, columns, rows, executionTime) {
        if (!reportSection || !reportTableHead || !reportTableBody) return;

        if (reportQueryText) reportQueryText.textContent = query;
        if (reportMetaCount) reportMetaCount.textContent = `${rows.length} row(s)`;
        if (reportMetaTime) reportMetaTime.textContent = `${executionTime}ms`;

        // Clear existing table content
        reportTableHead.innerHTML = '';
        reportTableBody.innerHTML = '';

        if (!columns || columns.length === 0) {
            reportTableHead.innerHTML = '<tr><th class="p-3 text-zinc-400 font-mono text-xs">No Columns</th></tr>';
            reportTableBody.innerHTML = '<tr><td class="p-3 text-zinc-500 font-mono text-xs">Query returned no result set.</td></tr>';
            reportSection.classList.remove('hidden');
            reportSection.scrollIntoView({ behavior: 'smooth' });
            return;
        }

        // Render table header
        const trHead = document.createElement('tr');
        trHead.className = 'bg-slate-100 text-slate-600 uppercase text-[10px] font-semibold border-b border-slate-200';
        columns.forEach((col, cIdx) => {
            const th = document.createElement('th');
            let stickyClass = '';
            if (cIdx === 0 && columns.length > 1) {
                stickyClass = 'sticky-col-1';
            } else if (cIdx === 1 && columns.length > 1) {
                stickyClass = 'sticky-col-2';
            }
            th.className = `px-3 py-2.5 text-[10px] uppercase tracking-wider font-mono font-semibold text-slate-600 whitespace-nowrap border-b border-slate-200 ${stickyClass}`;
            th.textContent = col;
            trHead.appendChild(th);
        });
        reportTableHead.appendChild(trHead);

        // Render table body
        if (rows.length === 0) {
            const emptyTr = document.createElement('tr');
            emptyTr.innerHTML = `<td colspan="${columns.length}" class="px-4 py-6 text-center text-slate-400 italic border-b border-slate-200">No records returned.</td>`;
            reportTableBody.appendChild(emptyTr);
        } else {
            rows.forEach((row) => {
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50 transition border-b border-slate-200';
                columns.forEach((col, cIdx) => {
                    const td = document.createElement('td');
                    let stickyClass = '';
                    if (cIdx === 0 && columns.length > 1) {
                        stickyClass = 'sticky-col-1';
                    } else if (cIdx === 1 && columns.length > 1) {
                        stickyClass = 'sticky-col-2';
                    }
                    td.className = `px-3 py-2.5 text-xs font-mono text-slate-800 whitespace-nowrap border-b border-slate-200 ${stickyClass}`;
                    const val = row[col];
                    if (val === null) {
                        td.innerHTML = '<span class="text-slate-400 italic">NULL</span>';
                    } else {
                        td.textContent = String(val);
                    }
                    tr.appendChild(td);
                });
                reportTableBody.appendChild(tr);
            });
        }

        // Show section and scroll down smoothly
        reportSection.classList.remove('hidden');

        // Dynamically compute offset for the 2nd sticky column so 1st and 2nd remain fixed on slide
        updateStickyColumnPositions();
        requestAnimationFrame(() => {
            updateStickyColumnPositions();
        });

        reportSection.scrollIntoView({ behavior: 'smooth' });
    }

    function updateStickyColumnPositions() {
        if (!reportTableHead) return;
        const firstCol = reportTableHead.querySelector('th.sticky-col-1');
        if (firstCol) {
            const col0Width = firstCol.getBoundingClientRect().width;
            if (col0Width > 0) {
                const secondCols = reportSection.querySelectorAll('.sticky-col-2');
                secondCols.forEach(el => {
                    el.style.left = `${col0Width}px`;
                });
            }
        }
    }

    window.addEventListener('resize', updateStickyColumnPositions);

    // Keyboard handlers: Enter inserts newline, Ctrl+Enter (or Cmd+Enter) executes query
    input.addEventListener('keydown', (e) => {
        // Execute on Ctrl+Enter or Cmd+Enter
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            form.requestSubmit();
            return;
        }

        // Allow standard Enter to insert a newline (default textarea behavior)
        if (e.key === 'Enter') {
            // Native behavior inserts \n, trigger height resize right after
            setTimeout(() => autoResizeTerminalTextarea(input), 0);
            return;
        }

        // History UP/DOWN arrows when at boundary
        if (e.key === 'ArrowUp' && (input.selectionStart === 0 && input.selectionEnd === 0)) {
            if (historyIndex > 0) {
                e.preventDefault();
                historyIndex--;
                input.value = history[historyIndex];
                autoResizeTerminalTextarea(input);
            }
        } else if (e.key === 'ArrowDown' && (input.selectionStart === input.value.length)) {
            if (historyIndex < history.length - 1) {
                e.preventDefault();
                historyIndex++;
                input.value = history[historyIndex];
                autoResizeTerminalTextarea(input);
            } else if (historyIndex === history.length - 1) {
                e.preventDefault();
                historyIndex = history.length;
                input.value = '';
                autoResizeTerminalTextarea(input);
            }
        }
    });

    function appendOutput(text, className = 'text-zinc-300') {
        const div = document.createElement('div');
        div.className = `whitespace-pre-wrap font-mono text-xs my-1 leading-relaxed ${className}`;
        div.textContent = text;
        output.appendChild(div);
        output.scrollTop = output.scrollHeight;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});
