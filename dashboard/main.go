package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/yinsights8/ai-job-search/dashboard/internal/data"
	"github.com/yinsights8/ai-job-search/dashboard/internal/model"
	"github.com/yinsights8/ai-job-search/dashboard/internal/theme"
	"github.com/yinsights8/ai-job-search/dashboard/internal/ui/screens"
)

type viewState int

const (
	viewPipeline viewState = iota
	viewProgress
)

type appModel struct {
	pipeline        screens.PipelineModel
	progress        screens.ProgressModel
	state           viewState
	repoRoot        string
	theme           theme.Theme
	progressMetrics model.ProgressMetrics
}

func (m *appModel) reloadPipelineData() {
	apps := data.ParseApplications(m.repoRoot)
	metrics := data.ComputeMetrics(apps)
	m.progressMetrics = data.ComputeProgressMetrics(apps)
	m.pipeline = m.pipeline.WithReloadedData(apps, metrics)
}

func (m appModel) Init() tea.Cmd {
	return nil
}

func (m appModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.pipeline.Resize(msg.Width, msg.Height)
		if m.state == viewProgress {
			m.progress.Resize(msg.Width, msg.Height)
		}
		pm, cmd := m.pipeline.Update(msg)
		m.pipeline = pm
		return m, cmd

	case screens.PipelineClosedMsg:
		return m, tea.Quit

	case screens.PipelineRefreshMsg:
		m.reloadPipelineData()
		return m, nil

	case screens.PipelineOpenProgressMsg:
		m.progress = screens.NewProgressModel(
			theme.NewTheme("auto"),
			m.progressMetrics,
			m.pipeline.Width(), m.pipeline.Height(),
		)
		m.state = viewProgress
		return m, nil

	case screens.ProgressClosedMsg:
		m.state = viewPipeline
		return m, nil

	default:
		if m.state == viewProgress {
			pg, cmd := m.progress.Update(msg)
			m.progress = pg
			return m, cmd
		}
		pm, cmd := m.pipeline.Update(msg)
		m.pipeline = pm
		return m, cmd
	}
}

func (m appModel) View() string {
	switch m.state {
	case viewProgress:
		return m.progress.View()
	default:
		return m.pipeline.View()
	}
}

func main() {
	pathFlag := flag.String("path", ".", "Path to ai-job-search repo root")
	flag.Parse()

	repoRoot := *pathFlag

	// Validate paths
	trackerPath := repoRoot + "/job_search_tracker.csv"
	seenPath := repoRoot + "/job_scraper/seen_jobs.json"

	if _, err := os.Stat(trackerPath); os.IsNotExist(err) {
		// Try alternate path
		if _, err2 := os.Stat(seenPath); os.IsNotExist(err2) {
			fmt.Fprintf(os.Stderr, "Error: could not find job data in %s\n", repoRoot)
			fmt.Fprintf(os.Stderr, "Expected: %s\n", trackerPath)
			fmt.Fprintf(os.Stderr, "       or: %s\n", seenPath)
			os.Exit(1)
		}
	}

	apps := data.ParseApplications(repoRoot)
	if apps == nil {
		fmt.Fprintf(os.Stderr, "Error: could not parse job data from %s\n", repoRoot)
		os.Exit(1)
	}

	metrics := data.ComputeMetrics(apps)
	progressMetrics := data.ComputeProgressMetrics(apps)

	t := theme.NewTheme("auto")
	pm := screens.NewPipelineModel(t, apps, metrics, repoRoot, 120, 40)

	m := appModel{
		pipeline:        pm,
		repoRoot:        repoRoot,
		theme:           t,
		progressMetrics: progressMetrics,
	}

	p := tea.NewProgram(m, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
