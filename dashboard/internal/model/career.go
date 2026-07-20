package model

// JobApplication represents a single job application from tracker + seen data.
type JobApplication struct {
	Number      int
	Date        string
	Company     string
	Role        string
	Status      string
	Score       float64
	ScoreRaw    string
	Location    string
	Salary      string
	SalaryMin   int
	SalaryMax   int
	Source      string
	Notes       string
	JobURL      string
	Fit         string // high, medium, low
	WorkMode    string
	LastContact string
}

// PipelineMetrics holds aggregate stats for the pipeline view.
type PipelineMetrics struct {
	Total      int
	ByStatus   map[string]int
	AvgScore   float64
	TopScore   float64
	Actionable int
}

// ProgressMetrics holds data for the analytics/progress view.
type ProgressMetrics struct {
	FunnelStages   []FunnelStage
	ScoreBuckets   []ScoreBucket
	WeeklyActivity []WeekActivity
	ResponseRate   float64
	InterviewRate  float64
	OfferRate      float64
	AvgScore       float64
	TopScore       float64
	TotalApplied   int
	TotalPreparing int
	ActiveApps     int
}

// FunnelStage represents one stage in the pipeline funnel.
type FunnelStage struct {
	Label string
	Count int
	Pct   float64
}

// ScoreBucket represents a score range and how many jobs fall in it.
type ScoreBucket struct {
	Label string
	Count int
}

// WeekActivity represents job activity for a calendar week.
type WeekActivity struct {
	Week  string
	Count int
}
