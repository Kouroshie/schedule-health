// Power Query (M) for the schedule-health pipeline.
// In Power BI Desktop: Home > Transform data > New Source > Blank Query > Advanced Editor,
// paste ONE query below per table, and name the query as shown. Set PipelineFolder to the
// full path of this powerbi folder (end it with a backslash). Then Close & Apply.
// After that, a daily pipeline run + Refresh (or a scheduled refresh in the Power BI
// service) updates every visual with no manual steps.

// ---- Query: Activities (current snapshot) ----
let
    PipelineFolder = "C:\Users\YOU\schedule-health\powerbi\",
    Source = Csv.Document(File.Contents(PipelineFolder & "current\activities.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"data_date", type date}, {"duration", Int64.Type},
        {"early_start", type date}, {"early_finish", type date}, {"late_finish", type date},
        {"total_float", Int64.Type}, {"free_float", Int64.Type}, {"critical", type logical},
        {"baseline_finish", type date}, {"slip_days", type number}}, "en-US")
in
    Typed

// ---- Query: NeedDates (current snapshot) ----
let
    PipelineFolder = "C:\Users\YOU\schedule-health\powerbi\",
    Source = Csv.Document(File.Contents(PipelineFolder & "current\need_dates.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"data_date", type date}, {"forecast_ready", type date}, {"need_date", type date},
        {"margin_days", Int64.Type}}, "en-US")
in
    Typed

// ---- Query: KpiHistory (one row per data date, for trend lines) ----
let
    PipelineFolder = "C:\Users\YOU\schedule-health\powerbi\",
    Source = Csv.Document(File.Contents(PipelineFolder & "history\kpis_history.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"data_date", type date}, {"forecast_finish", type date},
        {"critical_activities", Int64.Type}, {"worst_margin_days", Int64.Type},
        {"conflicts", Int64.Type}, {"watch", Int64.Type}, {"max_slip_days", type number},
        {"quality_checks", Int64.Type}}, "en-US")
in
    Typed

// ---- Query: NeedDateHistory (margin of every utility at every data date) ----
let
    PipelineFolder = "C:\Users\YOU\schedule-health\powerbi\",
    Source = Csv.Document(File.Contents(PipelineFolder & "history\need_dates_history.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"data_date", type date}, {"forecast_ready", type date}, {"need_date", type date},
        {"margin_days", Int64.Type}}, "en-US")
in
    Typed

// ---- Query: RefreshLog (show "last successful run" on the report) ----
let
    PipelineFolder = "C:\Users\YOU\schedule-health\powerbi\",
    Source = Csv.Document(File.Contents(PipelineFolder & "refresh_log.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"run_at", type datetime}, {"data_date", type date}}, "en-US")
in
    Typed

// Suggested DAX measures:
//   Last good run = CALCULATE(MAX(RefreshLog[run_at]), RefreshLog[status] = "OK")
//   Worst margin  = MIN(NeedDates[margin_days])
//   Finish change vs previous update (days) =
//       VAR d = MAX(KpiHistory[data_date])
//       VAR prev = CALCULATE(MAX(KpiHistory[data_date]), KpiHistory[data_date] < d)
//       RETURN DATEDIFF(CALCULATE(MAX(KpiHistory[forecast_finish]), KpiHistory[data_date] = prev),
//                       CALCULATE(MAX(KpiHistory[forecast_finish]), KpiHistory[data_date] = d), DAY)
