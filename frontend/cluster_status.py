def cluster_health_banner(status, connectivity, total_nodes, error_count):
    unreachable = [
        item for item in connectivity
        if item.get("status") == "unreachable"
    ]
    online_nodes = sum(
        1 for item in connectivity if item.get("status") == "reachable"
    )
    if unreachable:
        names = ", ".join(item.get("node_name", "unknown") for item in unreachable)
        return (
            "warning", "⚠️", "集群部分节点不可达",
            f"{online_nodes}/{total_nodes} 个节点网络可达，不可达节点：{names}",
        )
    if total_nodes == 0:
        return (
            "warning", "⚠️", "未发现注册节点",
            "无法从当前协调节点读取 pgxc_node 拓扑",
        )
    if total_nodes and len(connectivity) != total_nodes:
        return (
            "warning", "⚠️", "节点可达性未知",
            f"已注册 {total_nodes} 个节点，仅取得 {len(connectivity)} 项连通性结果",
        )
    if online_nodes < total_nodes:
        return (
            "warning", "⚠️", "节点状态未确认",
            f"{online_nodes}/{total_nodes} 个节点已确认网络可达",
        )
    if status == "partial":
        return (
            "warning", "⚠️", "集群状态采集不完整",
            f"所有节点网络可达，但有 {error_count} 项监控检查失败或超时",
        )
    return (
        "success", "✅", "集群运行正常",
        f"所有 {total_nodes} 个注册节点网络可达，系统运行健康",
    )
