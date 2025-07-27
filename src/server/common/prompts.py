# 监控类型基础配置
MONITOR_CONFIGS = {
    "告警": {
        "primary_table": "告警表(itinerant_db_alert_*)",
        "core_fields": "itinerant_date, alert_time, db_instance_id, business_subdomain, level, metric_name",
        "time_field": "itinerant_date",
        "agg_field": "COUNT(*) AS count",
        "default_sort": "count DESC",
        "default_viz": "response_table"
    },
    "隐患": {
        "primary_table": "隐患主表(itinerant_main)",
        "core_fields": "itinerant_date, created_time, db_instance_id, level, description",
        "time_field": "itinerant_date",
        "agg_field": "MAX(itinerant_value) AS max_value",
        "default_sort": "max_value DESC",
        "default_viz": "response_pie_chart"
    },
    "CPU": {
        "primary_table": "CPU性能表(itinerant_perf_cpu)",
        "core_fields": "collect_time, instance_id, cpu_usage, load_avg",
        "time_field": "collect_time",
        "agg_field": "MAX(cpu_usage) AS peak_cpu, AVG(cpu_usage) AS avg_cpu",
        "default_sort": "peak_cpu DESC",
        "default_viz": "response_line_chart"
    },
    "内存": {
        "primary_table": "内存性能表(itinerant_perf_mem)",
        "core_fields": "collect_time, instance_id, mem_usage, swap_usage",
        "time_field": "collect_time",
        "agg_field": "MAX(mem_usage) AS peak_mem, AVG(mem_usage) AS avg_mem",
        "default_sort": "peak_mem DESC",
        "default_viz": "response_line_chart"
    },
    "磁盘": {
        "primary_table": "磁盘性能表(itinerant_perf_disk)",
        "core_fields": "collect_time, instance_id, disk_usage, io_util",
        "time_field": "collect_time",
        "agg_field": "MAX(disk_usage) AS peak_disk, AVG(io_util) AS avg_io",
        "default_sort": "peak_disk DESC",
        "default_viz": "response_line_chart"
    },
    "网络": {
        "primary_table": "网络性能表(itinerant_perf_network)",
        "core_fields": "collect_time, instance_id, net_in, net_out",
        "time_field": "collect_time",
        "agg_field": "MAX(net_in) AS peak_in, MAX(net_out) AS peak_out",
        "default_sort": "peak_in DESC",
        "default_viz": "response_line_chart"
    }
}
