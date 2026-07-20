package screens

import (
	"fmt"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/muesli/termenv"

	"github.com/yinsights8/ai-job-search/dashboard/internal/data"
	"github.com/yinsights8/ai-job-search/dashboard/internal/model"
	"github.com/yinsights8/ai-job-search/dashboard/internal/theme"
)

type PipelineClosedMsg struct{}
type PipelineOpenProgressMsg struct{}
type PipelineRefreshMsg struct{}

type pipelineTab struct {
	filter string
	label  string
}

var pipelineTabs = []pipelineTab{
	{"all", "ALL"},
	{"new", "NEW"},
	{"evaluated", "EVALUATED"},
	{"preparing", "PREPARING"},
	{"applied", "APPLIED"},
	{"skipped", "SKIPPED"},
}

type statusOption struct {
	label string
	value string
}

var statusOptions = []statusOption{
	{"Evaluated", "evaluated"},
	{"Applied", "applied"},
	{"Responded", "responded"},
	{"Interview", "interview"},
	{"Offer", "offer"},
	{"Rejected", "rejected"},
	{"Discarded", "discarded"},
	{"SKIP", "skip"},
}

type PipelineModel struct {
	apps          []model.JobApplication
	filtered      []model.JobApplication
	metrics       model.PipelineMetrics
	cursor        int
	sortMode      string
	activeTab     int
	width, height int
	theme         theme.Theme
	repoRoot      string

	changingStatus bool
	statusCursor   int
	statusMsg      string
}

func NewPipelineModel(t theme.Theme, apps []model.JobApplication, metrics model.PipelineMetrics, repoRoot string, width, height int) PipelineModel {
	m := PipelineModel{
		apps:     apps,
		metrics:  metrics,
		sortMode: "score",
		theme:    t,
		repoRoot: repoRoot,
		width:    width,
		height:   height,
	}
	m.filtered = m.applyFilter()
	return m
}

func (m PipelineModel) Init() tea.Cmd { return nil }

func (m *PipelineModel) Resize(width, height int) {
	m.width = width
	m.height = height
}

func (m PipelineModel) Width() int  { return m.width }
func (m PipelineModel) Height() int { return m.height }

func (m PipelineModel) WithReloadedData(apps []model.JobApplication, metrics model.PipelineMetrics) PipelineModel {
	m.apps = apps
	m.metrics = metrics
	m.filtered = m.applyFilter()
	return m
}

func (m *PipelineModel) applyFilter() []model.JobApplication {
	tab := pipelineTabs[m.activeTab].filter
	var result []model.JobApplication

	for _, app := range m.apps {
		status := data.NormalizeStatus(app.Status)
		switch tab {
		case "all":
			result = append(result, app)
		case "new":
			if status == "new" {
				result = append(result, app)
			}
		case "evaluated":
			if status == "evaluated" {
				result = append(result, app)
			}
		case "preparing":
			if status == "preparing" {
				result = append(result, app)
			}
		case "applied":
			if status == "applied" {
				result = append(result, app)
			}
		case "skipped":
			if status == "skip" {
				result = append(result, app)
			}
		}
	}

	// Sort
	sort.Slice(result, func(i, j int) bool {
		a, b := result[i], result[j]
		switch m.sortMode {
		case "score":
			return a.Score > b.Score
		case "date":
			return a.Date > b.Date
		case "company":
			return strings.ToLower(a.Company) < strings.ToLower(b.Company)
		case "pay":
			return a.SalaryMax > b.SalaryMax
		default:
			return a.Score > b.Score
		}
	})

	return result
}

func (m PipelineModel) Update(msg tea.Msg) (PipelineModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		if m.changingStatus {
			return m.updateStatusPicker(msg)
		}

		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		case "p":
			return m, func() tea.Msg { return PipelineOpenProgressMsg{} }
		case "r":
			return m, func() tea.Msg { return PipelineRefreshMsg{} }
		case "c":
			if len(m.filtered) > 0 {
				m.changingStatus = true
				m.statusCursor = 0
				m.statusMsg = ""
			}
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < len(m.filtered)-1 {
				m.cursor++
			}
		case "left", "h":
			if m.activeTab > 0 {
				m.activeTab--
				m.cursor = 0
				m.filtered = m.applyFilter()
			}
		case "right", "l":
			if m.activeTab < len(pipelineTabs)-1 {
				m.activeTab++
				m.cursor = 0
				m.filtered = m.applyFilter()
			}
		case "tab":
			m.activeTab = (m.activeTab + 1) % len(pipelineTabs)
			m.cursor = 0
			m.filtered = m.applyFilter()
		case "s":
			modes := []string{"score", "date", "company", "pay"}
			for i, mode := range modes {
				if mode == m.sortMode {
					m.sortMode = modes[(i+1)%len(modes)]
					break
				}
			}
			m.filtered = m.applyFilter()
		}
	}
	return m, nil
}

func (m PipelineModel) updateStatusPicker(msg tea.KeyMsg) (PipelineModel, tea.Cmd) {
	switch msg.String() {
	case "esc", "c":
		m.changingStatus = false
		m.statusMsg = ""
	case "up", "k":
		if m.statusCursor > 0 {
			m.statusCursor--
		}
	case "down", "j":
		if m.statusCursor < len(statusOptions)-1 {
			m.statusCursor++
		}
	case "enter":
		if m.cursor < len(m.filtered) {
			selected := m.filtered[m.cursor]
			newStatus := statusOptions[m.statusCursor].value
			err := data.WriteTrackerStatus(m.repoRoot, selected.Company, selected.Role, newStatus)
			if err != nil {
				m.statusMsg = "Error: " + err.Error()
			} else {
				m.statusMsg = fmt.Sprintf("%s \u2192 %s", selected.Company, statusOptions[m.statusCursor].label)
			}
			m.changingStatus = false
			return m, func() tea.Msg { return PipelineRefreshMsg{} }
		}
	}
	return m, nil
}

func (m PipelineModel) View() string {
	lipgloss.SetColorProfile(termenv.ANSI256)
	t := m.theme

	// Header
	header := m.renderHeader(t)

	// Tabs
	tabs := m.renderTabs(t)

	// Metrics bar
	metricsBar := m.renderMetricsBar(t)

	// Table
	table := m.renderTable(t)

	// Footer
	footer := m.renderFooter(t)

	content := lipgloss.JoinVertical(lipgloss.Left, header, tabs, metricsBar, "", table, "", footer)

	// Fill to full terminal height BEFORE overlay
	contentLines := strings.Count(content, "\n") + 1
	if contentLines < m.height {
		remaining := m.height - contentLines
		content += strings.Repeat("\n", remaining)
	}

	if m.changingStatus {
		modal := m.renderStatusPicker(t)
		content = overlayCenter(content, modal, m.width, m.height)
	}

	return content
}

func (m PipelineModel) renderHeader(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Blue).
		Render("  CAREER PIPELINE")

	total := lipgloss.NewStyle().Foreground(t.Sky).Bold(true).Render(fmt.Sprintf("%d jobs", m.metrics.Total))
	sep := lipgloss.NewStyle().Foreground(t.Subtext).Render(" | ")
	applied := lipgloss.NewStyle().Foreground(t.Green).Bold(true).Render(fmt.Sprintf("%d applied", m.metrics.ByStatus["applied"]+m.metrics.ByStatus["preparing_application"]))
	avg := "N/A"
	if m.metrics.AvgScore > 0 {
		avg = fmt.Sprintf("%.1f", m.metrics.AvgScore)
	}
	avgText := lipgloss.NewStyle().Foreground(t.Yellow).Bold(true).Render("Avg " + avg + "/5")

	stats := total + sep + applied + sep + avgText

	bar := lipgloss.NewStyle().
		Background(t.Surface).
		Foreground(t.Text).
		Width(m.width).
		Render(title + "  " + stats)

	return bar
}

func (m PipelineModel) renderTabs(t theme.Theme) string {
	var parts []string

	for i, tab := range pipelineTabs {
		count := 0
		for _, app := range m.apps {
			status := data.NormalizeStatus(app.Status)
			if tab.filter == "all" {
				count++
			} else if status == tab.filter {
				count++
			}
		}

		label := tab.label
		style := lipgloss.NewStyle().Foreground(t.Subtext)

		if i == m.activeTab {
			style = style.Foreground(t.Blue).Bold(true).Underline(true)
		} else if count > 0 {
			style = style.Foreground(t.Text)
		} else {
			style = style.Foreground(t.Subtext)
		}

		parts = append(parts, style.Render(fmt.Sprintf("%s(%d)", label, count)))
	}

	return strings.Join(parts, "  ")
}

func (m PipelineModel) renderMetricsBar(t theme.Theme) string {
	interview := lipgloss.NewStyle().Foreground(t.Subtext).Render("interview:") +
		lipgloss.NewStyle().Foreground(t.Green).Bold(true).Render(fmt.Sprintf("%d", m.metrics.ByStatus["interview"]))

	applied := lipgloss.NewStyle().Foreground(t.Subtext).Render("applied:") +
		lipgloss.NewStyle().Foreground(t.Sky).Bold(true).Render(fmt.Sprintf("%d", m.metrics.ByStatus["applied"]))

	preparing := lipgloss.NewStyle().Foreground(t.Subtext).Render("preparing:") +
		lipgloss.NewStyle().Foreground(t.Yellow).Bold(true).Render(fmt.Sprintf("%d", m.metrics.ByStatus["preparing_application"]))

	evaluated := lipgloss.NewStyle().Foreground(t.Subtext).Render("evaluated:") +
		lipgloss.NewStyle().Foreground(t.Text).Bold(true).Render(fmt.Sprintf("%d", m.metrics.ByStatus["evaluated"]))

	skipped := lipgloss.NewStyle().Foreground(t.Subtext).Render("skipped:") +
		lipgloss.NewStyle().Foreground(t.Red).Bold(true).Render(fmt.Sprintf("%d", m.metrics.ByStatus["skipped"]))

	bar := lipgloss.NewStyle().
		Background(t.Surface).
		Foreground(t.Text).
		Width(m.width).
		Render("  " + interview + "  " + applied + "  " + preparing + "  " + evaluated + "  " + skipped)

	return bar
}

func (m PipelineModel) renderTable(t theme.Theme) string {
	// Column headers
	numW, fitW, dateW, companyW, roleW, statusW, salaryW := 4, 6, 12, 24, 30, 16, 18

	headers := []string{
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(numW).Render("#"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(fitW).Align(lipgloss.Center).Render("FIT"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(dateW).Render("APPLIED"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(companyW).Render("COMPANY"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(roleW).Render("ROLE"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(statusW).Render("STATUS"),
		lipgloss.NewStyle().Bold(true).Foreground(t.Subtext).Width(salaryW).Render("SALARY"),
	}

	divider := lipgloss.NewStyle().Foreground(t.Overlay).Width(m.width).Render(strings.Repeat("\u2500", m.width-2))

	var lines []string
	lines = append(lines, strings.Join(headers, " "))
	lines = append(lines, divider)

	// Data rows
	visibleStart := 0
	visibleEnd := len(m.filtered)
	maxRows := m.height - 10 // leave room for header/tabs/footer
	if maxRows < 5 {
		maxRows = 5
	}

	if len(m.filtered) > maxRows {
		// Scroll to keep cursor visible
		if m.cursor >= maxRows {
			visibleStart = m.cursor - maxRows + 1
		}
		visibleEnd = visibleStart + maxRows
		if visibleEnd > len(m.filtered) {
			visibleEnd = len(m.filtered)
		}
	}

	for i := visibleStart; i < visibleEnd; i++ {
		app := m.filtered[i]
		row := m.renderRow(t, app, i == m.cursor)
		lines = append(lines, row)
	}

	return strings.Join(lines, "\n")
}

func (m PipelineModel) renderRow(t theme.Theme, app model.JobApplication, selected bool) string {
	numW, fitW, dateW, companyW, roleW, statusW, salaryW := 4, 6, 12, 24, 30, 16, 18

	bg := t.Base
	if selected {
		bg = t.Overlay
	}

	rowStyle := lipgloss.NewStyle().Background(bg)

	// Score color
	scoreColor := t.Text
	switch {
	case app.Score >= 4.2:
		scoreColor = t.Green
	case app.Score >= 3.8:
		scoreColor = t.Yellow
	case app.Score >= 3.0:
		scoreColor = t.Text
	default:
		scoreColor = t.Red
	}

	// Status color
	statusColor := t.Text
	statusLabel := app.Status
	switch data.NormalizeStatus(app.Status) {
	case "applied":
		statusColor = t.Sky
		statusLabel = "Applied"
	case "preparing":
		statusColor = t.Yellow
		statusLabel = "Preparing"
	case "evaluated":
		statusColor = t.Text
		statusLabel = "Evaluated"
	case "new":
		statusColor = t.Subtext
		statusLabel = "New"
	case "responded":
		statusColor = t.Blue
		statusLabel = "Responded"
	case "interview":
		statusColor = t.Green
		statusLabel = "Interview"
	case "offer":
		statusColor = t.Green
		statusLabel = "Offer"
	case "rejected":
		statusColor = t.Red
		statusLabel = "Rejected"
	case "discarded":
		statusColor = t.Red
		statusLabel = "Discarded"
	case "skip":
		statusColor = t.Red
		statusLabel = "Skipped"
	}

	scoreStr := fmt.Sprintf("%.1f", app.Score)
	if app.Score == 0 {
		scoreStr = "-"
	}

	num := rowStyle.Width(numW).Render(truncate(fmt.Sprintf("%d", app.Number), numW))
	fit := rowStyle.Width(fitW).Align(lipgloss.Center).Foreground(scoreColor).Bold(true).Render(truncate(scoreStr, fitW))
	date := rowStyle.Width(dateW).Foreground(t.Subtext).Render(truncate(app.Date, dateW))
	company := rowStyle.Width(companyW).Foreground(t.Text).Bold(selected).Render(truncate(app.Company, companyW))
	role := rowStyle.Width(roleW).Render(truncate(app.Role, roleW))
	status := rowStyle.Width(statusW).Foreground(statusColor).Bold(true).Render(truncate(statusLabel, statusW))
	salary := rowStyle.Width(salaryW).Foreground(t.Sky).Render(truncate(app.Salary, salaryW))

	return strings.Join([]string{num, fit, date, company, role, status, salary}, " ")
}

func (m PipelineModel) renderFooter(t theme.Theme) string {
	help := lipgloss.NewStyle().
		Foreground(t.Subtext).
		Render("  \u2191\u2193/jk nav  \u2190\u2192/hl tabs  s sort  c status  r refresh  p progress  q quit")

	brand := lipgloss.NewStyle().
		Foreground(t.Overlay).
		Render("job-dashboard by yinsights8")

	bar := lipgloss.NewStyle().
		Background(t.Surface).
		Foreground(t.Text).
		Width(m.width).
		Render(help + "  " + brand)

	return bar
}

func (m PipelineModel) renderStatusPicker(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Blue).
		Render("Change Status")

	var lines []string
	lines = append(lines, title)
	lines = append(lines, "")

	for i, opt := range statusOptions {
		cursor := "  "
		style := lipgloss.NewStyle().Foreground(t.Text)
		if i == m.statusCursor {
			cursor = lipgloss.NewStyle().Foreground(t.Blue).Bold(true).Render("> ")
			style = style.Foreground(t.Blue).Bold(true)
		}
		lines = append(lines, cursor+style.Render(opt.label))
	}

	lines = append(lines, "")
	lines = append(lines, lipgloss.NewStyle().Foreground(t.Subtext).Render("enter select  esc cancel"))

	content := strings.Join(lines, "\n")

	boxW := 24
	boxH := len(lines) + 2
	border := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(t.Blue).
		Width(boxW).
		Height(boxH).
		Padding(0, 1).
		Render(content)

	return border
}

func overlayCenter(bg, fg string, width, height int) string {
	bgLines := strings.Split(bg, "\n")
	fgLines := strings.Split(fg, "\n")

	fgH := len(fgLines)
	fgW := 0
	for _, l := range fgLines {
		w := lipgloss.Width(l)
		if w > fgW {
			fgW = w
		}
	}

	startY := (height - fgH) / 2
	if startY < 0 {
		startY = 0
	}
	startX := (width - fgW) / 2
	if startX < 0 {
		startX = 0
	}

	for i, fl := range fgLines {
		y := startY + i
		if y >= len(bgLines) {
			break
		}
		fw := lipgloss.Width(fl)
		prefixW := 0
		prefix := ""
		for prefixW < startX && prefixW+1 <= startX {
			prefix += " "
			prefixW++
		}
		suffixW := width - prefixW - fw
		suffix := ""
		for suffixW > 0 {
			suffix += " "
			suffixW--
		}
		bgLines[y] = prefix + fl + suffix
	}

	return strings.Join(bgLines, "\n")
}

func truncate(s string, max int) string {
	if max <= 0 {
		return ""
	}
	if len(s) <= max {
		return s
	}
	if max <= 1 {
		return "\u2026"
	}
	return s[:max-1] + "\u2026"
}
