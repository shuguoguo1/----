# D题基础航段计算器

本项目实现《山区洪涝灾害下无人机运输与通信协同优化》的底层航段计算引擎。当前范围严格限定为单航段几何、时间、等效航程和能耗计算，不包含货箱组批、VRP、电池排程、通信中继或任何启发式优化算法。

## 1. 实际读取的附件

程序以 `D_PROBLEM_ROOT` 环境变量或 `src/config.py` 中的默认根目录为入口，递归自动发现：

- `山区洪涝灾害下无人机运输与通信协同优化.docx`
- `调度中心与服务区.xlsx`
- `运输无人机数据.xlsx`
- `镇龙乡及周边30米DEM.tif`
- `镇龙乡地理空间数据说明.pdf`

附件只读取一次，DEM、节点、机型和节点对几何均在内存中缓存。

## 2. 识别出的运输无人机参数

程序从 Excel 读取三种机型 A/B/C 的以下字段：

- 含电池空载总质量、最大载货质量、可用装载体积
- 计划巡航速度、空载标准航程、满载标准航程
- 电池可用能量、返航电量下限
- 固定准备时间、每箱装载时间
- 接收点基础交接时间、每箱增加交接时间
- 最大爬升速度、最大下降速度
- 爬升能耗效率、下降能耗效率

所有赛题参数均集中从附件读取；代码只在 `src/config.py` 维护统一规则常数与单位换算常数。

## 3. 飞行时间公式

计划巡航海拔为航段沿线最高DEM高程加50 m。O01作业海拔等于地面海拔，服务区作业海拔等于地面海拔加30 m。

航段飞行时间严格按题面附录2实现：

```text
t_total = h_climb / v_climb
        + horizontal_distance / v_cruise
        + h_descend / v_descend
```

## 4. 等效航程与能耗

等效航程严格按题面公式实现：

```text
L_g(q) = L_g^0 - (L_g^0 - L_g^F) * (q / Q_g)^(3/2)
```

### 公式待人工核对

题面公式对象明确给出了 `E_total = E_horizontal + E_climb`，但没有给出两个分项的显式公式。为使基础计算器可以运行和测试，当前将二者分别封装为：

```text
E_horizontal = E_use * horizontal_distance / L_g(q)
E_climb = (empty_mass_with_battery + payload) * g * h_climb
          / climb_efficiency / 3_600_000
```

这是根据“等效航程”和“爬升能耗效率”的量纲关系作出的可复核解释，不宣称为题面已明确给出的公式。正式竞赛提交前必须由参赛队根据命题方补充说明或原始公式再次核验。实现集中在 `src/flight_calculator.py` 的 `horizontal_energy_kwh()` 和 `climb_energy_kwh()`，便于核验后单点替换。

## 5. DEM与距离处理

- 读取GeoTIFF的像元尺度、地理 tie point、GeoKey、NoData。
- 校验坐标系为WGS84（EPSG:4326）。
- 使用 `pyproj.Geod(ellps="WGS84")` 计算准确测地距离。
- 沿测地航线按不超过15 m的间隔采样，高程采用对应DEM像元值。
- 排除NoData=-32767，返回最大高程及其大致经纬度。
- 不使用起终点高程代替航线中间地形。

## 6. 单位

- 长度、海拔、高度：m
- 时间：s
- 质量：kg
- 能量：kWh
- 经纬度：degree

变量名和CSV表头均携带单位后缀。

## 7. 使用方法

安装依赖后运行测试：

```powershell
python -m pytest -q
```

生成全部基础输出：

```powershell
python generate_outputs.py
```

也可以指定赛题根目录和输出目录：

```powershell
python generate_outputs.py --problem-root "D:\比赛\...\D题" --output-dir outputs
```

核心接口：

```python
from src.flight_calculator import calculate_segment

result = calculate_segment(
    start_node="O01",
    end_node="S001",
    model_id="A",
    payload_kg=20.0,
)
```

## 8. 输出文件

- `outputs/node_pair_geometry.csv`：16个节点之间240个有向节点对的几何与DEM结果。
- `outputs/segment_demo.csv`：O01到S001、A型、20 kg的完整示例。
- `outputs/segment_cost_demo.csv`：三种机型、多个典型载荷和多条路线的成本示例。
- `outputs/demo_elevation_profile.png`：DEM高程剖面验证图。
- `outputs/demo_elevation_profile.svg`：同一剖面的矢量版本。
- `outputs/demo_elevation_profile_grayscale.png`：灰度可读性检查版本。

## 9. 测试覆盖

测试包括：

1. O01到S001空载计算；
2. 接近最大载荷时等效航程下降、能耗增加；
3. 不同方向和不同海拔服务区的地形差异；
4. S001到S002的非O01航段；
5. 超载和负载荷的明确错误；
6. DEM采样间隔、最高点和高程剖面一致性；
7. 16个节点240个有向节点对的完整性。

## 10. 当前需要人工核验的事项

唯一实质性歧义是水平能耗与爬升附加能耗的分项公式。其余距离、DEM、巡航高度、作业高度、升降时间和等效航程均可从附件直接确定。
