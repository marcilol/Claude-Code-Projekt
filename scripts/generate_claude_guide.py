# -*- coding: utf-8 -*-
"""Generate Claude Code & Max Guide as Word document."""

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import datetime


def set_cell_shading(cell, color):
    shading = cell._element.get_or_add_tcPr()
    shd = shading.makeelement(qn('w:shd'), {qn('w:fill'): color, qn('w:val'): 'clear'})
    shading.append(shd)


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(255, 255, 255)
        set_cell_shading(cell, '2F5496')
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
            if r_idx % 2 == 1:
                set_cell_shading(cell, 'D6E4F0')
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)
    return table


def build_document():
    doc = Document()

    # Title
    doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run('Claude Code & Claude Max')
    run.font.size = Pt(32)
    run.bold = True
    run.font.color.rgb = RGBColor(47, 84, 150)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run('A Practical Guide for the Portfolio X-Ray Project')
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(89, 89, 89)

    doc.add_paragraph()
    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = date_p.add_run(datetime.date.today().strftime('%B %d, %Y'))
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(89, 89, 89)

    doc.add_page_break()

    # ================================================================
    # 1. What is Claude Code?
    # ================================================================
    doc.add_heading('1. What is Claude Code?', level=1)
    doc.add_paragraph(
        'Claude Code is an AI coding agent that runs in your terminal, VS Code, JetBrains, '
        'or browser. Unlike a chatbot, it can read your entire codebase, edit files, run '
        'commands, search the web, and execute multi-step tasks autonomously. Think of it as '
        'a senior developer pair-programming with you 24/7.'
    )
    doc.add_paragraph('How it works:')
    steps = [
        'You describe what you want in plain English (or paste an error, screenshot, etc.)',
        'Claude reads relevant files, searches your codebase, and understands the context',
        'It proposes changes, edits files, runs tests, and iterates until the task is done',
        'You review and approve changes at each step (or let it run autonomously)',
    ]
    for i, s in enumerate(steps, 1):
        doc.add_paragraph(f'{i}. {s}')

    doc.add_heading('1.1 How This Applies to Portfolio X-Ray', level=2)
    doc.add_paragraph(
        'You have already been using Claude Code to build this project. Every script in '
        'scripts/, the CLAUDE.md file, the CNE5 factor computations, the R\u00b2 fix \u2014 all of '
        'these were built interactively with Claude Code reading your codebase, understanding '
        'the Barra methodology, and writing Python code. This guide shows you how to do more '
        'of this, more efficiently, as the project grows.'
    )

    doc.add_page_break()

    # ================================================================
    # 2. Subscription Plans
    # ================================================================
    doc.add_heading('2. Subscription Plans & Access', level=1)

    plans = [
        ('Claude Pro', '$20/month', 'Includes Claude Code. Access to Sonnet and Opus models. Good for individual use with moderate usage.'),
        ('Claude Max 5x', '$40/month', '5x the usage of Pro. Good for heavy daily use on a single project.'),
        ('Claude Max 20x', '$100/month', '20x the usage of Pro. Recommended for intensive development like building Portfolio X-Ray.'),
        ('Claude Max 40x', '$200/month', '40x usage. For power users running multiple parallel sessions.'),
        ('API (Pay-as-you-go)', 'Per token', 'Sonnet: $3/$15 per 1M tokens (in/out). Opus: $15/$45. No monthly commitment. Best for automation and programmatic use.'),
    ]
    add_table(doc, ['Plan', 'Cost', 'Details'], plans, col_widths=[3.5, 2.5, 11])

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Recommendation for your project: ')
    run.bold = True
    p.add_run(
        'Claude Max 20x ($100/month) gives you enough headroom for daily heavy development '
        'sessions. If your collaborator also subscribes, you each get independent usage. '
        'The API pay-as-you-go option is useful later for automating tasks (e.g., scheduled '
        'data pipeline runs using the Claude Agent SDK).'
    )

    doc.add_page_break()

    # ================================================================
    # 3. Getting Started
    # ================================================================
    doc.add_heading('3. Getting Started', level=1)

    doc.add_heading('3.1 Installation', level=2)
    doc.add_paragraph('Install Claude Code on your system:')
    install = [
        ('Windows', 'winget install Anthropic.ClaudeCode'),
        ('macOS', 'brew install --cask claude-code'),
        ('Linux', 'curl -fsSL https://claude.ai/install.sh | bash'),
        ('npm (any OS)', 'npm install -g @anthropic-ai/claude-code'),
    ]
    add_table(doc, ['Platform', 'Command'], install, col_widths=[3, 14])

    doc.add_heading('3.2 First Session', level=2)
    doc.add_paragraph('Open a terminal in your project directory and run:')
    doc.add_paragraph('    claude', style='No Spacing')
    doc.add_paragraph(
        'Claude will read your CLAUDE.md (which you already have), load your auto-memory, '
        'and be ready to work. You can immediately ask it to do things like:'
    )
    examples = [
        '"Run the factor model and tell me the new R\u00b2"',
        '"Add a short-term reversal factor to fetch_data.py"',
        '"Create a Streamlit page that uploads a portfolio CSV and shows risk decomposition"',
        '"Review my changes before I commit"',
    ]
    for ex in examples:
        doc.add_paragraph(ex, style='List Bullet')

    doc.add_heading('3.3 IDE Integration (VS Code)', level=2)
    doc.add_paragraph(
        'Install the Claude Code extension from the VS Code marketplace. This gives you '
        'Claude in a sidebar panel with diff review, file @-mentions, and inline plan editing. '
        'Use Cmd/Ctrl+Esc to toggle focus between your code and Claude.'
    )

    doc.add_page_break()

    # ================================================================
    # 4. CLAUDE.md & Auto Memory
    # ================================================================
    doc.add_heading('4. CLAUDE.md & Auto Memory', level=1)

    doc.add_heading('4.1 CLAUDE.md (Project Instructions)', level=2)
    doc.add_paragraph(
        'You already have a comprehensive CLAUDE.md. This is loaded at the start of every '
        'session and tells Claude about your project structure, factor model methodology, '
        'file formats, and key commands. Keep it updated as the project evolves.'
    )
    doc.add_paragraph('Best practices:')
    practices = [
        'Keep it under 200 lines \u2014 move detailed notes to separate files linked from CLAUDE.md',
        'Include build/test commands so Claude can verify its own work',
        'Document naming conventions and coding patterns',
        'Commit CLAUDE.md to git so your collaborator gets the same instructions',
    ]
    for p_text in practices:
        doc.add_paragraph(p_text, style='List Bullet')

    doc.add_heading('4.2 Auto Memory', level=2)
    doc.add_paragraph(
        'Claude automatically saves learnings across sessions in '
        '~/.claude/projects/<project>/memory/MEMORY.md. You already have this \u2014 it contains '
        'gotchas like "factor covariance is in DAILY units" and patterns like "pandas groupby.apply '
        'corrupts indices." These persist across conversations so Claude doesn\'t repeat mistakes.'
    )

    doc.add_page_break()

    # ================================================================
    # 5. Key Workflows for Portfolio X-Ray
    # ================================================================
    doc.add_heading('5. Key Workflows for Your Project', level=1)

    doc.add_heading('5.1 Building the Streamlit Front-End', level=2)
    doc.add_paragraph('Tell Claude:')
    doc.add_paragraph(
        '    "Create a Streamlit app with 6 pages: Upload, Risk Analysis, Optimization, '
        'Sizing, Risk Management, and Model Status. Start with the Upload page."',
        style='No Spacing'
    )
    doc.add_paragraph(
        'Claude will read your existing scripts, understand the data flow, and create the '
        'Streamlit pages that reuse your existing computation functions. It can run the app '
        'locally to test it.'
    )

    doc.add_heading('5.2 Integrating EODHD API', level=2)
    doc.add_paragraph('Tell Claude:')
    doc.add_paragraph(
        '    "Replace yfinance with EODHD in fetch_data.py. Here is my EODHD API key: [key]. '
        'Fetch daily prices, quarterly fundamentals, analyst consensus estimates (forward EPS), '
        'and GICS sub-industry codes. Keep the --compute-only flag working."',
        style='No Spacing'
    )
    doc.add_paragraph(
        'Claude will read the existing fetch_data.py, understand the data structures, '
        'and rewrite the fetching functions while preserving the downstream pipeline.'
    )

    doc.add_heading('5.3 Excel Verification Model', level=2)
    doc.add_paragraph('Tell Claude:')
    doc.add_paragraph(
        '    "Create an Excel workbook that replicates the factor model for 20 stocks and '
        '5 trading days. Include sheets for raw data, factor exposures, z-scoring, cross-sectional '
        'regression, and a reconciliation sheet comparing Excel vs Python outputs."',
        style='No Spacing'
    )

    doc.add_heading('5.4 Writing Tests', level=2)
    doc.add_paragraph('Tell Claude:')
    doc.add_paragraph(
        '    "Write pytest unit tests for the z-scoring, beta computation, composite factor '
        'calculation, and orthogonalization functions in fetch_data.py. Use known inputs with '
        'hand-calculated expected outputs."',
        style='No Spacing'
    )

    doc.add_heading('5.5 Code Review & Commits', level=2)
    doc.add_paragraph(
        'Use /commit to have Claude create well-formatted git commits. Use /review-pr to '
        'review pull requests from your collaborator. Claude will read the diff, check for '
        'bugs, and suggest improvements.'
    )

    doc.add_heading('5.6 Debugging Data Issues', level=2)
    doc.add_paragraph(
        'Paste an error or describe unexpected behavior. Claude will read the relevant code, '
        'add diagnostic prints, run the script, analyze the output, and fix the issue \u2014 '
        'often in a single session.'
    )

    doc.add_page_break()

    # ================================================================
    # 6. Essential Keyboard Shortcuts
    # ================================================================
    doc.add_heading('6. Essential Keyboard Shortcuts', level=1)

    shortcuts = [
        ('Shift+Tab', 'Cycle permission modes (default \u2192 plan \u2192 auto)'),
        ('Esc Esc', 'Rewind or undo last action'),
        ('Ctrl+C', 'Cancel current generation'),
        ('Ctrl+L', 'Clear screen (keeps history)'),
        ('Shift+Enter', 'Multi-line input (new line without sending)'),
        ('!command', 'Run a shell command directly (e.g., !git status)'),
        ('/commit', 'Create a git commit with Claude-written message'),
        ('/plan', 'Enter plan mode (explore before making changes)'),
        ('/compact', 'Manually compress context to free space'),
        ('/context', 'See what is consuming your context window'),
        ('@filename', 'Reference a specific file in your prompt'),
        ('Alt+P', 'Switch models mid-session (e.g., Opus \u2192 Sonnet)'),
    ]
    add_table(doc, ['Shortcut', 'Action'], shortcuts, col_widths=[3.5, 13.5])

    doc.add_page_break()

    # ================================================================
    # 7. Permission Modes
    # ================================================================
    doc.add_heading('7. Permission Modes', level=1)
    doc.add_paragraph(
        'Claude Code has different permission levels that control how much autonomy Claude has. '
        'Cycle between them with Shift+Tab.'
    )

    modes = [
        ('Default', 'Claude asks permission before editing files or running commands. Best for sensitive work. You approve each change.'),
        ('Plan Mode', 'Claude can only read and explore \u2014 no edits allowed. Perfect for "investigate this issue" or "design an approach" before committing to changes. Use /plan to enter.'),
        ('Accept Edits', 'Claude can edit files without asking, but still asks before running commands. Good when you are iterating quickly and reviewing diffs.'),
        ('Auto Mode', 'Full autonomy: Claude reads, writes, and runs commands without asking. Use for long tasks like "set up the entire Streamlit app." Monitor the output and Ctrl+C if it goes wrong.'),
    ]
    add_table(doc, ['Mode', 'Behavior'], modes, col_widths=[3, 14])

    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run('Recommendation: ')
    run.bold = True
    p.add_run(
        'Use Default mode for financial model changes (accuracy matters). Use Plan mode to '
        'explore approaches. Use Auto mode for boilerplate work like setting up Streamlit pages '
        'or writing tests.'
    )

    doc.add_page_break()

    # ================================================================
    # 8. MCP Servers
    # ================================================================
    doc.add_heading('8. MCP Servers (External Tool Integration)', level=1)
    doc.add_paragraph(
        'MCP (Model Context Protocol) lets Claude connect to external services. '
        'For Portfolio X-Ray, useful MCP servers include:'
    )

    mcp = [
        ('GitHub', 'Manage PRs, issues, and code reviews directly from Claude', 'claude mcp add --transport http github https://api.githubcopilot.com/mcp/'),
        ('PostgreSQL', 'Query your DuckDB or Postgres database', 'claude mcp add --transport stdio db -- npx -y @bytebase/dbhub --dsn "..."'),
        ('Sentry', 'Monitor errors in your data pipeline', 'claude mcp add --transport http sentry https://mcp.sentry.dev/mcp'),
        ('Slack', 'Send analysis results to a channel', 'claude mcp add --transport http slack https://api.slack.com/mcp'),
        ('Playwright', 'Automate browser testing of Streamlit app', 'claude mcp add --transport stdio pw -- npx @playwright/mcp@latest'),
    ]
    add_table(doc, ['Server', 'Use Case', 'Install Command'], mcp, col_widths=[2.5, 6, 8.5])

    doc.add_paragraph()
    doc.add_paragraph(
        'Project-scoped MCP servers (stored in .mcp.json) are shared with your collaborator '
        'via git. User-scoped servers (in ~/.claude.json) are personal.'
    )

    doc.add_page_break()

    # ================================================================
    # 9. Two-Person Collaboration
    # ================================================================
    doc.add_heading('9. Collaborating with a Partner', level=1)

    doc.add_heading('9.1 What Gets Shared via Git', level=2)
    shared = [
        ('CLAUDE.md', 'Project instructions \u2014 both developers see the same rules', 'Committed'),
        ('.claude/settings.json', 'Shared permissions and tool configurations', 'Committed'),
        ('.mcp.json', 'Project-scoped MCP servers', 'Committed'),
        ('.claude/settings.local.json', 'Personal settings overrides', 'Git-ignored'),
        ('~/.claude/CLAUDE.md', 'Personal preferences (applies to all projects)', 'Local only'),
        ('Auto memory (MEMORY.md)', 'Each developer builds their own memory', 'Local only'),
        ('Conversation history', 'Each session is independent', 'Local only'),
    ]
    add_table(doc, ['File', 'Purpose', 'Scope'], shared, col_widths=[4.5, 9, 3.5])

    doc.add_heading('9.2 Workflow for Two Developers', level=2)
    workflow = [
        'Each developer installs Claude Code and authenticates with their own subscription',
        'Both clone the same GitHub repo (CLAUDE.md and .claude/settings.json are shared)',
        'Each works on feature branches: Person A on backend, Person B on frontend',
        'Use Claude /commit to create commits with good messages',
        'Open PRs on GitHub; use Claude /review-pr to review each other\'s code',
        'Merge via GitHub (squash and merge recommended)',
        'Claude\'s auto-memory learns each developer\'s patterns independently',
    ]
    for i, w in enumerate(workflow, 1):
        doc.add_paragraph(f'{i}. {w}')

    doc.add_heading('9.3 Dividing the Work', level=2)
    doc.add_paragraph(
        'To minimize merge conflicts, divide by component. Claude Code makes both people '
        'more productive, but the work should still be clearly partitioned:'
    )
    division = [
        ('Person A (Backend)', 'Factor model improvements, EODHD integration, data pipeline, DuckDB migration, unit tests, Excel verification model'),
        ('Person B (Frontend)', 'Streamlit app, visualization, deployment, user documentation, CI/CD pipeline, scheduling'),
        ('Both', 'Architecture decisions, code reviews, CLAUDE.md updates, project planning'),
    ]
    add_table(doc, ['Role', 'Tasks'], division, col_widths=[3.5, 13.5])

    doc.add_page_break()

    # ================================================================
    # 10. Hooks for Automation
    # ================================================================
    doc.add_heading('10. Hooks for Project Automation', level=1)
    doc.add_paragraph(
        'Hooks run shell commands automatically at specific points in Claude\'s workflow. '
        'Configure them in .claude/settings.json.'
    )

    hooks = [
        ('Auto-format Python', 'PostToolUse (Edit/Write)', 'Run black on every edited file automatically'),
        ('Protect model data', 'PreToolUse (Edit/Write)', 'Block edits to data/model/*.csv (prevent accidental overwrites)'),
        ('Run tests after changes', 'PostToolUse (Edit)', 'Run pytest after editing scripts/*.py'),
        ('Notify on completion', 'Stop', 'Send a desktop notification when Claude finishes a long task'),
        ('Reload context', 'SessionStart', 'Re-inject critical context after session compaction'),
    ]
    add_table(doc, ['Hook', 'Event', 'What It Does'], hooks, col_widths=[4, 4, 9])

    doc.add_page_break()

    # ================================================================
    # 11. Claude API for Automation
    # ================================================================
    doc.add_heading('11. Claude API & Agent SDK for Automation', level=1)
    doc.add_paragraph(
        'Beyond interactive use, Claude can be used programmatically via the API and Agent SDK. '
        'This is relevant for automating parts of the Portfolio X-Ray pipeline.'
    )

    doc.add_heading('11.1 Use Cases', level=2)
    api_uses = [
        ('Automated Report Generation', 'After the daily data update completes, call Claude API to generate a natural-language summary of factor model changes, new risk alerts, and portfolio recommendations. Email or post to Slack.'),
        ('Intelligent Data Validation', 'After fetching from EODHD, use Claude to review the data for anomalies (e.g., "AAPL market cap dropped 90% \u2014 likely a data error"). Much smarter than simple threshold checks.'),
        ('Portfolio Analysis API', 'Wrap the analysis scripts in a FastAPI endpoint. Use Claude to generate natural-language explanations of the risk decomposition results for non-technical users.'),
        ('Scheduled Code Maintenance', 'Use the Agent SDK to periodically scan for dependency updates, security issues, or code quality improvements.'),
    ]
    add_table(doc, ['Use Case', 'How'], api_uses, col_widths=[4, 13])

    doc.add_heading('11.2 Agent SDK Quick Start', level=2)
    doc.add_paragraph('Install: pip install claude-agent-sdk')
    doc.add_paragraph(
        'The Agent SDK gives Claude access to file reading, writing, shell commands, '
        'and web search \u2014 the same tools it has in Claude Code, but callable from '
        'your Python scripts. This lets you build automated agents that maintain your '
        'codebase, generate reports, or run analysis pipelines.'
    )

    doc.add_page_break()

    # ================================================================
    # 12. Cost Management
    # ================================================================
    doc.add_heading('12. Managing Costs', level=1)

    doc.add_paragraph('Tips to get the most out of your subscription:')
    cost_tips = [
        ('Keep CLAUDE.md concise', 'Every token in CLAUDE.md is sent with every message. 200 lines is enough.'),
        ('Use /compact proactively', 'When context fills up, Claude compresses old messages. Do it before hitting limits.'),
        ('Switch models with Alt+P', 'Use Opus for complex reasoning (factor model changes). Use Sonnet for routine tasks (formatting, boilerplate, tests).'),
        ('Use Plan mode for exploration', 'Plan mode is read-only. Cheaper than letting Claude write code you will throw away.'),
        ('Delegate to subagents', 'For search-heavy tasks, Claude spawns lightweight agents that protect your main context.'),
        ('Run /cost periodically', 'See how many tokens you have used in the current session.'),
    ]
    add_table(doc, ['Tip', 'Why'], cost_tips, col_widths=[5, 12])

    doc.add_page_break()

    # ================================================================
    # 13. Mapping Claude Code to the Project Plan
    # ================================================================
    doc.add_heading('13. How Claude Code Accelerates Each Phase', level=1)

    doc.add_paragraph(
        'Here is how Claude Code directly helps with each phase from the Project Plan:'
    )

    mapping = [
        ('Phase 1: Foundation', 'Excel verification model', 'Ask Claude to generate the openpyxl workbook with formulas. It reads your existing code and replicates the math in Excel.'),
        ('Phase 1: Foundation', 'Unit tests', 'Ask Claude to write pytest tests. It understands the functions, generates test data, and runs the tests to verify they pass.'),
        ('Phase 1: Foundation', 'DuckDB migration', 'Ask Claude to convert CSV-loading code to DuckDB queries. It reads every script, finds pd.read_csv calls, and rewrites them.'),
        ('Phase 1: Foundation', 'Streamlit MVP', 'Ask Claude to create the app. It reads your CLI scripts, extracts the computation logic, and wraps it in Streamlit widgets.'),
        ('Phase 2: Data Quality', 'EODHD integration', 'Give Claude the API docs (paste URL or PDF). It redesigns fetch_data.py to use the new API.'),
        ('Phase 2: Data Quality', 'GICS upgrade', 'Ask Claude to map 11 sectors to 25+ industry groups. It reads the data, creates the mapping, updates all scripts.'),
        ('Phase 2: Data Quality', 'Analyst estimates', 'Ask Claude to add EPFWD and EGRLF descriptors. It understands the CNE5 spec and factor weights.'),
        ('Phase 3: Polish', 'Full Streamlit app', 'Build one page at a time. Claude creates each page, connects it to the backend, and tests it.'),
        ('Phase 3: Polish', 'Deployment', 'Ask Claude to create a Dockerfile, Railway config, or Streamlit Cloud setup. It handles the infrastructure boilerplate.'),
        ('Phase 4: Expansion', 'International markets', 'Ask Claude to extend fetch_data.py for non-US exchanges. It handles currency, calendar, and data source differences.'),
    ]
    add_table(doc, ['Phase', 'Task', 'How Claude Code Helps'], mapping, col_widths=[3, 3.5, 10.5])

    doc.add_page_break()

    # ================================================================
    # 14. Resources
    # ================================================================
    doc.add_heading('14. Resources & Links', level=1)

    resources = [
        ('Claude Code Documentation', 'https://code.claude.com/docs'),
        ('Claude Code Overview', 'https://code.claude.com/docs/en/overview'),
        ('CLAUDE.md Guide', 'https://code.claude.com/docs/en/memory'),
        ('Hooks Guide', 'https://code.claude.com/docs/en/hooks-guide'),
        ('MCP Servers', 'https://code.claude.com/docs/en/mcp'),
        ('VS Code Extension', 'https://code.claude.com/docs/en/vs-code'),
        ('Permission Modes', 'https://code.claude.com/docs/en/permission-modes'),
        ('Agent SDK (Python)', 'https://github.com/anthropics/claude-agent-sdk-python'),
        ('Claude API Docs', 'https://platform.claude.com/docs'),
        ('Anthropic Pricing', 'https://www.anthropic.com/pricing'),
        ('Claude Max Plans', 'https://support.claude.com/en/articles/11145838'),
        ('GitHub: Portfolio X-Ray', '(your repo URL here)'),
    ]
    add_table(doc, ['Resource', 'URL'], resources, col_widths=[5, 12])

    # Save
    output_path = 'Claude_Code_Guide.docx'
    doc.save(output_path)
    print(f'Saved: {output_path}')


if __name__ == '__main__':
    build_document()
