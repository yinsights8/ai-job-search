package screens

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/yinsights8/ai-job-search/dashboard/internal/model"
	"github.com/yinsights8/ai-job-search/dashboard/internal/theme"
)

type ProgressClosedMsg struct{}

const barBlock = "\u2588"

type ProgressModel struct {
	metrics      model.ProgressMetrics
	scrollOffset int
	width        int
	height       int
	theme        theme.Theme
}

func NewProgressModel(t theme.Theme, metrics model.ProgressMetrics, width, height int) ProgressModel {
	return ProgressModel{
		metrics: metrics,
		width:   width,
		height:  height,
		theme:   t,
	}
}

func (m ProgressModel) Init() tea.Cmd { return nil }

func (m *ProgressModel) Resize(width, height int) {
	m.width = width
	m.height = height
}

func (m ProgressModel) Update(msg tea.Msg) (ProgressModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "esc", "ctrl+c":
			return m, func() tea.Msg { return ProgressClosedMsg{} }
		case "down", "j":
			m.scrollOffset++
		case "up", "k":
			if m.scrollOffset > 0 {
				m.scrollOffset--
			}
		case "pgdown":
			m.scrollOffset += m.height - 4
		case "pgup":
			m.scrollOffset -= m.height - 4
			if m.scrollOffset < 0 {
				m.scrollOffset = 0
			}
		}
	}
	return m, nil
}

func (m ProgressModel) View() string {
	t := m.theme

	var sections []string

	// Header
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Mauve).
		Render("  SEARCH PROGRESS")

	stats := lipgloss.NewStyle().
		Foreground(t.Sky).
		Bold(true).
		Render(fmt.Sprintf("  %d evaluated", m.metrics.ActiveApps))

	avg := "N/A"
	if m.metrics.AvgScore > 0 {
		avg = fmt.Sprintf("%.1f", m.metrics.AvgScore)
	}
	avgText := lipgloss.NewStyle().
		Foreground(t.Yellow).
		Bold(true).
		Render(fmt.Sprintf(" | %s avg", avg))

	header := lipgloss.NewStyle().
		Background(t.Surface).
		Foreground(t.Text).
		Width(m.width).
		Render(title + stats + avgText)

	sections = append(sections, header, "")

	// Funnel
	sections = append(sections, m.renderFunnel(t))
	sections = append(sections, "")

	// Score distribution
	sections = append(sections, m.renderScoreDistribution(t))
	sections = append(sections, "")

	// Conversion rates
	sections = append(sections, m.renderConversionRates(t))
	sections = append(sections, "")

	// Weekly activity
	if len(m.metrics.WeeklyActivity) > 0 {
		sections = append(sections, m.renderWeeklyActivity(t))
		sections = append(sections, "")
	}

	// Footer
	footer := lipgloss.NewStyle().
		Foreground(t.Subtext).
		Render("  \u2191\u2193 scroll  pgup/pgdn page  esc back     job-dashboard by yinsights8")

	bar := lipgloss.NewStyle().
		Background(t.Surface).
		Width(m.width).
		Render(footer)

	sections = append(sections, bar)

	content := strings.Join(sections, "\n")

	// Apply scroll offset
	lines := strings.Split(content, "\n")
	if m.scrollOffset > 0 && m.scrollOffset < len(lines) {
		lines = lines[m.scrollOffset:]
	}
	if len(lines) > m.height {
		lines = lines[:m.height]
	}

	return strings.Join(lines, "\n")
}

func (m ProgressModel) renderFunnel(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Mauve).
		Render("  Pipeline Funnel")

	sections := []string{title}

	// Find max for scaling
	maxCount := 0
	for _, stage := range m.metrics.FunnelStages {
		if stage.Count > maxCount {
			maxCount = stage.Count
		}
	}

	// Gradient colors for funnel
	colors := []lipgloss.Color{t.Blue, t.Sky, t.Green, t.Yellow, t.Peach}

	for i, stage := range m.metrics.FunnelStages {
		color := t.Text
		if i < len(colors) {
			color = colors[i]
		}

		barWidth := 40
		filled := 0
		if maxCount > 0 && stage.Count > 0 {
			filled = stage.Count * barWidth / maxCount
			if filled == 0 {
				filled = 1
			}
		}
		empty := barWidth - filled

		bar := lipgloss.NewStyle().Foreground(color).Render(strings.Repeat(barBlock, filled))
		bar += lipgloss.NewStyle().Foreground(t.Overlay).Render(strings.Repeat(" ", empty))

		countText := lipgloss.NewStyle().
			Foreground(color).
			Bold(true).
			Render(fmt.Sprintf("  %d", stage.Count))

		label := lipgloss.NewStyle().
			Foreground(color).
			Bold(true).
			Render(fmt.Sprintf("  %-12s", stage.Label))

		sections = append(sections, label+bar+countText)
	}

	return strings.Join(sections, "\n")
}

func (m ProgressModel) renderScoreDistribution(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Mauve).
		Render("  Score Distribution")

	sections := []string{title}

	// Find max for scaling
	maxCount := 0
	for _, bucket := range m.metrics.ScoreBuckets {
		if bucket.Count > maxCount {
			maxCount = bucket.Count
		}
	}

	// Colors from good to bad
	colors := []lipgloss.Color{t.Green, t.Green, t.Yellow, t.Peach, t.Red}

	for i, bucket := range m.metrics.ScoreBuckets {
		color := t.Text
		if i < len(colors) {
			color = colors[i]
		}

		barWidth := 40
		filled := 0
		if maxCount > 0 && bucket.Count > 0 {
			filled = bucket.Count * barWidth / maxCount
			if filled == 0 {
				filled = 1
			}
		}
		empty := barWidth - filled

		bar := lipgloss.NewStyle().Foreground(color).Render(strings.Repeat(barBlock, filled))
		bar += lipgloss.NewStyle().Foreground(t.Overlay).Render(strings.Repeat(" ", empty))

		countText := lipgloss.NewStyle().
			Foreground(color).
			Bold(true).
			Render(fmt.Sprintf("  %d", bucket.Count))

		label := lipgloss.NewStyle().
			Foreground(color).
			Bold(true).
			Render(fmt.Sprintf("  %-12s", bucket.Label))

		sections = append(sections, label+bar+countText)
	}

	return strings.Join(sections, "\n")
}

func (m ProgressModel) renderConversionRates(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Mauve).
		Render("  Conversion Rates")

	sections := []string{title}

	rateColor := func(rate float64) lipgloss.Color {
		switch {
		case rate >= 30:
			return t.Green
		case rate >= 15:
			return t.Yellow
		case rate >= 5:
			return t.Peach
		default:
			return t.Red
		}
	}

	rr := m.metrics.ResponseRate
	ir := m.metrics.InterviewRate
	or := m.metrics.OfferRate

	line1 := lipgloss.NewStyle().Foreground(t.Subtext).Render("  Response Rate: ") +
		lipgloss.NewStyle().Foreground(rateColor(rr)).Bold(true).Render(fmt.Sprintf("%.1f%%", rr)) +
		lipgloss.NewStyle().Foreground(t.Subtext).Render("  |  ") +
		lipgloss.NewStyle().Foreground(t.Subtext).Render("Interview Rate: ") +
		lipgloss.NewStyle().Foreground(rateColor(ir)).Bold(true).Render(fmt.Sprintf("%.1f%%", ir)) +
		lipgloss.NewStyle().Foreground(t.Subtext).Render("  |  ") +
		lipgloss.NewStyle().Foreground(t.Subtext).Render("Offer Rate: ") +
		lipgloss.NewStyle().Foreground(rateColor(or)).Bold(true).Render(fmt.Sprintf("%.1f%%", or))

	line2 := lipgloss.NewStyle().Foreground(t.Sky).Bold(true).
		Render(fmt.Sprintf("  %d active applications", m.metrics.ActiveApps)) +
		lipgloss.NewStyle().Foreground(t.Subtext).Render(" | ") +
		lipgloss.NewStyle().Foreground(t.Subtext).Render(fmt.Sprintf("%d total offers", 0))

	sections = append(sections, line1, line2)
	return strings.Join(sections, "\n")
}

func (m ProgressModel) renderWeeklyActivity(t theme.Theme) string {
	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(t.Mauve).
		Render("  Weekly Activity")

	sections := []string{title}

	// Find max for scaling
	maxCount := 0
	for _, week := range m.metrics.WeeklyActivity {
		if week.Count > maxCount {
			maxCount = week.Count
		}
	}

	for _, week := range m.metrics.WeeklyActivity {
		barWidth := 40
		filled := 0
		if maxCount > 0 && week.Count > 0 {
			filled = week.Count * barWidth / maxCount
			if filled == 0 {
				filled = 1
			}
		}
		empty := barWidth - filled

		bar := lipgloss.NewStyle().Foreground(t.Sky).Render(strings.Repeat(barBlock, filled))
		bar += lipgloss.NewStyle().Foreground(t.Overlay).Render(strings.Repeat(" ", empty))

		countText := lipgloss.NewStyle().
			Foreground(t.Sky).
			Bold(true).
			Render(fmt.Sprintf("  %d", week.Count))

		label := lipgloss.NewStyle().
			Foreground(t.Sky).
			Bold(true).
			Render(fmt.Sprintf("  %-12s", week.Week))

		sections = append(sections, label+bar+countText)
	}

	return strings.Join(sections, "\n")
}
