# College Majors 演示问题 / Demo Questions

上传并选择 `recent-grads.csv`、`all-ages.csv`、`grad-students.csv` 和 `majors-list.csv`。 / Upload and select `recent-grads.csv`, `all-ages.csv`, `grad-students.csv`, and `majors-list.csv`.

## 1. 多表关联质量 / Cross-file join quality

中文：用 Major_code 作为键检查 recent-grads、all-ages、grad-students 和 majors-list 的关联：共同专业有多少个？每张表各有多少个无法匹配的代码？

English: Use Major_code as the join key across recent-grads, all-ages, grad-students, and majors-list. How many majors are common to all four files, and how many codes in each file fail to match?

## 2. 专业类别就业表现 / Outcomes by major category

中文：在 recent-grads 中按 Major_category 分组，计算每类 Median 的中位数和 Unemployment_rate 的平均值；列出收入最高、失业率最低的类别及其数值。

English: In recent-grads, group by Major_category and calculate the median of Median and the mean of Unemployment_rate for each category. Report the category with the highest income and the category with the lowest unemployment, with their values.

## 3. 不同年龄口径收入差异 / Earnings across age groups

中文：按 Major_code 对齐 recent-grads 和 all-ages，计算每个专业的 Median(all-ages) - Median(recent-grads)，列出差值最大的五个专业。

English: Join recent-grads and all-ages by Major_code. For each major, calculate Median(all-ages) minus Median(recent-grads), and list the five largest gaps.

## 4. 高收入低失业专业 / High-earning, low-unemployment majors

中文：在 recent-grads 中筛选 Median 不低于 50000 且 Unemployment_rate 低于 0.05 的专业，并按 Median 从高到低列出。

English: In recent-grads, filter for majors with Median at least 50000 and Unemployment_rate below 0.05, then list them in descending order of Median.
