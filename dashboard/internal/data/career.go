package data

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/yinsights8/ai-job-search/dashboard/internal/model"
)

var reScore = regexp.MustCompile(`(\d+)/100`)
var reSalary = regexp.MustCompile(`(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)`)

// ParseApplications reads job_search_tracker.csv and seen_jobs.json, merges them.
func ParseApplications(repoRoot string) []model.JobApplication {
	trackerPath := filepath.Join(repoRoot, "job_search_tracker.csv")
	seenPath := filepath.Join(repoRoot, "job_scraper", "seen_jobs.json")

	tracker := parseTracker(trackerPath)
	seen := parseSeen(seenPath)

	return mergeApplications(tracker, seen)
}

func parseTracker(path string) []model.JobApplication {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	reader := csv.NewReader(f)
	records, err := reader.ReadAll()
	if err != nil {
		return nil
	}

	var apps []model.JobApplication
	for i, row := range records {
		if i == 0 {
			continue // skip header
		}
		if len(row) < 8 {
			continue
		}

		app := model.JobApplication{
			Number:  i,
			Date:    row[0],
			Company: row[1],
			Role:    row[2],
			Location: row[3],
			Salary:  row[4],
			Source:  row[5],
			Status:  row[6],
			Notes:   row[7],
		}

		// Parse salary
		if m := reSalary.FindStringSubmatch(app.Salary); len(m) == 3 {
			app.SalaryMin = parseMoney(m[1])
			app.SalaryMax = parseMoney(m[2])
		}

		// Parse fit score from notes
		if m := reScore.FindStringSubmatch(app.Notes); len(m) == 2 {
			if v, err := strconv.ParseFloat(m[1], 64); err == nil {
				app.Score = v / 20.0 // 0-100 -> 0-5
				app.ScoreRaw = m[1] + "/100"
			}
		}

		// Derive work mode
		lower := strings.ToLower(app.Location + " " + app.Notes)
		switch {
		case strings.Contains(lower, "remote"):
			app.WorkMode = "Remote"
		case strings.Contains(lower, "hybrid"):
			app.WorkMode = "Hybrid"
		default:
			app.WorkMode = "On-site"
		}

		apps = append(apps, app)
	}
	return apps
}

func parseSeen(path string) map[string]model.JobApplication {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	var data struct {
		Seen map[string]struct {
			Title     string `json:"title"`
			Company   string `json:"company"`
			URL       string `json:"url"`
			Location  string `json:"location"`
			Salary    string `json:"salary"`
			Deadline  string `json:"deadline"`
			FirstSeen string `json:"first_seen"`
			Fit       string `json:"fit"`
			Status    string `json:"status"`
			Source    string `json:"source"`
		} `json:"seen"`
	}

	if err := json.NewDecoder(f).Decode(&data); err != nil {
		return nil
	}

	result := make(map[string]model.JobApplication)
	for key, v := range data.Seen {
		app := model.JobApplication{
			Company:    v.Company,
			Role:       v.Title,
			Location:   v.Location,
			Salary:     v.Salary,
			Date:       v.FirstSeen,
			Fit:        v.Fit,
			Status:     v.Status,
			Source:     v.Source,
			JobURL:     v.URL,
			LastContact: v.Deadline,
		}

		// Score from fit category
		switch v.Fit {
		case "high":
			app.Score = 4.5
		case "medium":
			app.Score = 3.8
		case "low":
			app.Score = 2.5
		default:
			app.Score = 3.0
		}
		app.ScoreRaw = v.Fit

		// Parse salary
		if m := reSalary.FindStringSubmatch(v.Salary); len(m) == 3 {
			app.SalaryMin = parseMoney(m[1])
			app.SalaryMax = parseMoney(m[2])
		}

		// Derive work mode
		lower := strings.ToLower(v.Location)
		switch {
		case strings.Contains(lower, "remote"):
			app.WorkMode = "Remote"
		case strings.Contains(lower, "hybrid"):
			app.WorkMode = "Hybrid"
		default:
			app.WorkMode = "On-site"
		}

		result[key] = app
	}
	return result
}

func mergeApplications(tracker []model.JobApplication, seen map[string]model.JobApplication) []model.JobApplication {
	seenMatched := make(map[string]bool)
	var result []model.JobApplication

	// Add tracker entries first (authoritative)
	for _, app := range tracker {
		// Try to find matching seen entry
		for key, sv := range seen {
			if seenMatched[key] {
				continue
			}
			if companiesMatch(sv.Company, app.Company) || rolesMatch(sv.Role, app.Role) {
				if app.JobURL == "" {
					app.JobURL = sv.JobURL
				}
				if app.Fit == "" {
					app.Fit = sv.Fit
				}
				seenMatched[key] = true
				break
			}
		}
		result = append(result, app)
	}

	// Add unmatched seen entries
	for key, app := range seen {
		if seenMatched[key] {
			continue
		}
		app.Number = len(result) + 1
		result = append(result, app)
	}

	// Re-number
	for i := range result {
		result[i].Number = i + 1
	}

	return result
}

func companiesMatch(c1, c2 string) bool {
	c1, c2 = strings.ToLower(strings.TrimSpace(c1)), strings.ToLower(strings.TrimSpace(c2))
	if c1 == c2 {
		return true
	}
	if strings.Contains(c1, c2) || strings.Contains(c2, c1) {
		return true
	}
	return false
}

func rolesMatch(r1, r2 string) bool {
	r1, r2 = strings.ToLower(r1), strings.ToLower(r2)
	if r1 == r2 {
		return true
	}
	if strings.Contains(r1, r2) || strings.Contains(r2, r1) {
		return true
	}
	return false
}

func parseMoney(s string) int {
	s = strings.ReplaceAll(s, ",", "")
	s = strings.TrimSpace(s)
	v, _ := strconv.Atoi(s)
	return v
}

// ComputeMetrics calculates pipeline-level aggregate stats.
func ComputeMetrics(apps []model.JobApplication) model.PipelineMetrics {
	m := model.PipelineMetrics{
		ByStatus: make(map[string]int),
		Total:    len(apps),
	}

	for _, app := range apps {
		m.ByStatus[app.Status]++
		if app.Score > m.TopScore {
			m.TopScore = app.Score
		}
	}

	totalScore := 0.0
	count := 0
	for _, app := range apps {
		if app.Score > 0 {
			totalScore += app.Score
			count++
		}
	}
	if count > 0 {
		m.AvgScore = totalScore / float64(count)
	}

	m.Actionable = m.ByStatus["applied"] + m.ByStatus["preparing_application"] + m.ByStatus["evaluated"]
	return m
}

// ComputeProgressMetrics calculates analytics for the progress screen.
func ComputeProgressMetrics(apps []model.JobApplication) model.ProgressMetrics {
	pm := model.ProgressMetrics{}

	statusCounts := make(map[string]int)
	for _, app := range apps {
		statusCounts[app.Status]++
	}

	// Funnel stages
	total := len(apps)
	applied := statusCounts["applied"]
	preparing := statusCounts["preparing_application"]
	evaluated := statusCounts["evaluated"]
	active := applied + preparing

	pm.FunnelStages = []model.FunnelStage{
		{Label: "Seen", Count: total, Pct: pct(total, total)},
		{Label: "Active", Count: active, Pct: pct(active, total)},
		{Label: "Applied", Count: applied, Pct: pct(applied, total)},
		{Label: "Preparing", Count: preparing, Pct: pct(preparing, total)},
		{Label: "Evaluated", Count: evaluated, Pct: pct(evaluated, total)},
	}

	// Score buckets
	buckets := map[string]int{
		"4.5-5.0": 0, "4.0-4.4": 0, "3.5-3.9": 0,
		"3.0-3.4": 0, "<3.0": 0,
	}
	for _, app := range apps {
		switch {
		case app.Score >= 4.5:
			buckets["4.5-5.0"]++
		case app.Score >= 4.0:
			buckets["4.0-4.4"]++
		case app.Score >= 3.5:
			buckets["3.5-3.9"]++
		case app.Score >= 3.0:
			buckets["3.0-3.4"]++
		default:
			buckets["<3.0"]++
		}
	}
	pm.ScoreBuckets = []model.ScoreBucket{
		{Label: "4.5-5.0", Count: buckets["4.5-5.0"]},
		{Label: "4.0-4.4", Count: buckets["4.0-4.4"]},
		{Label: "3.5-3.9", Count: buckets["3.5-3.9"]},
		{Label: "3.0-3.4", Count: buckets["3.0-3.4"]},
		{Label: "<3.0", Count: buckets["<3.0"]},
	}

	// Rates
	pm.TotalApplied = applied
	pm.TotalPreparing = preparing
	pm.ActiveApps = active
	if total > 0 {
		pm.ResponseRate = float64(active) / float64(total) * 100
	}

	// Avg / top score
	totalScore := 0.0
	scoreCount := 0
	for _, app := range apps {
		if app.Score > 0 {
			totalScore += app.Score
			scoreCount++
			if app.Score > pm.TopScore {
				pm.TopScore = app.Score
			}
		}
	}
	if scoreCount > 0 {
		pm.AvgScore = totalScore / float64(scoreCount)
	}

	// Weekly activity (group by ISO week from date)
	weekCounts := make(map[string]int)
	for _, app := range apps {
		if app.Date == "" {
			continue
		}
		if len(app.Date) >= 10 {
			week := app.Date[:10] // simplified: use date as week bucket
			weekCounts[week]++
		}
	}

	// Sort weeks
	var weeks []string
	for w := range weekCounts {
		weeks = append(weeks, w)
	}
	sort.Strings(weeks)
	for _, w := range weeks {
		pm.WeeklyActivity = append(pm.WeeklyActivity, model.WeekActivity{
			Week:  w,
			Count: weekCounts[w],
		})
	}

	return pm
}

func pct(part, total int) float64 {
	if total == 0 {
		return 0
	}
	return float64(part) / float64(total) * 100
}

// WriteTrackerStatus updates the status of a job in job_search_tracker.csv.
// It matches by company and role name.
func WriteTrackerStatus(repoRoot, company, role, newStatus string) error {
	path := filepath.Join(repoRoot, "job_search_tracker.csv")

	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open tracker: %w", err)
	}
	reader := csv.NewReader(f)
	records, err := reader.ReadAll()
	f.Close()
	if err != nil {
		return fmt.Errorf("read tracker: %w", err)
	}

	found := false
	for i, row := range records {
		if i == 0 {
			continue
		}
		if len(row) < 8 {
			continue
		}
		if companiesMatch(row[1], company) && rolesMatch(row[2], role) {
			records[i][6] = newStatus
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("job not found: %s / %s", company, role)
	}

	out, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create tracker: %w", err)
	}
	defer out.Close()

	w := csv.NewWriter(out)
	if err := w.WriteAll(records); err != nil {
		return fmt.Errorf("write tracker: %w", err)
	}
	return nil
}

// NormalizeStatus maps tracker statuses to canonical values.
func NormalizeStatus(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "applied":
		return "applied"
	case "preparing_application", "preparing":
		return "preparing"
	case "evaluated":
		return "evaluated"
	case "new":
		return "new"
	case "responded":
		return "responded"
	case "interview":
		return "interview"
	case "offer":
		return "offer"
	case "rejected":
		return "rejected"
	case "discarded":
		return "discarded"
	case "skipped", "skip":
		return "skip"
	default:
		return raw
	}
}

// StatusPriority returns sort key for status ordering.
func StatusPriority(status string) int {
	switch status {
	case "interview":
		return 0
	case "offer":
		return 1
	case "applied":
		return 2
	case "preparing":
		return 3
	case "evaluated":
		return 4
	case "new":
		return 5
	case "skip":
		return 6
	default:
		return 7
	}
}

func init() {
	_ = fmt.Sprintf // ensure fmt is used
}
