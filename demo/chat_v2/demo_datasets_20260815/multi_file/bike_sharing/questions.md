# UCI Bike Sharing 演示问题 / Demo Questions

上传并选择 `day.csv`、`hour.csv` 和 `Readme.txt`。 / Upload and select `day.csv`, `hour.csv`, and `Readme.txt`.

## 完整需求分析

请联合分析日级和小时级共享单车数据：

1. 先按日期汇总 `hour.csv` 的 `casual`、`registered` 和 `cnt`，与 `day.csv` 对应字段核对。报告不一致的日期数量和最大差异，不要默认两个文件一定一致。
2. 比较 2011 与 2012 的总骑行量和同比增幅，并区分注册用户与临时用户。
3. 工作日与非工作日的小时使用曲线有何不同？分别指出高峰小时。
4. 天气状况与骑行量有什么关联？请同时报告各天气类别的样本数，避免用极少样本得出强结论。

请生成日级趋势图、工作日/非工作日小时曲线图、星期×小时热力图，以及一张数据一致性检查表。最后给出 4 条面向运营人员的结论。将图表保存为文件。

## Full demand analysis

Analyze the daily and hourly bike-sharing data together:

1. Aggregate `casual`, `registered`, and `cnt` from `hour.csv` by date and reconcile them with the corresponding fields in `day.csv`. Report the number of mismatched dates and the largest difference instead of assuming the files agree.
2. Compare total rides in 2011 and 2012 and calculate year-over-year growth, separating registered from casual users.
3. How do hourly usage curves differ between working and non-working days? Identify the peak hours for each.
4. How is weather associated with ride volume? Also report sample counts for every weather category so that rare categories do not support overly strong conclusions.

Create a daily trend chart, working-day versus non-working-day hourly curves, a weekday-by-hour heatmap, and a data-consistency table. Finish with four findings for operations staff and save all charts and tables as files.

## 快速高峰对比 / Quick peak comparison

中文：验证日表是否等于小时表按天汇总的结果，并用图说明工作日和周末的骑行高峰有什么不同。

English: Verify whether the daily table equals the hourly table aggregated by date, then use a chart to show how ride peaks differ between working days and weekends.
