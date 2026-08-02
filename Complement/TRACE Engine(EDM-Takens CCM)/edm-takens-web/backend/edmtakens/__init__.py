# EDM-Takens Web — Backend Package
#
# 模块以 sibling-style 裸导入（from pipeline import ...），
# 由 backend/api.py 在启动时将本目录插入 sys.path[0]。
#
# 注意：本目录下的模块与 edm-takens/src/ 同名（复制副本），
# 但 _paths.py 的数据路径指向 web 上下文（回引 edm-takens 数据目录）。
# 切勿将 edm-takens/src/ 和本目录同时加入 sys.path，否则会触发模块遮蔽。
