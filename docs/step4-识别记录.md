# 第 4 步识别记录 · tests/fixtures/samples · 2026-10-14

> 这一批是自制测试样本（`tests/fixtures/samples/make_samples.py` 生成，非客户资料），用来验证读取流程。真实样本（清单 G1、G2）到了以后用同一个命令再跑一次，结果追加在下面。生成命令：`python -m app.extract.report <样本文件夹>`。

| 文件 | 等级 | 读取方式 | 认出的字段（值 · 置信度 · 位置） |
| --- | --- | --- | --- |
| Concept_render.png | C 仅作参考，不用于计算 | 先文字识别，再读尺寸 | 未找到尺寸，仅作参考 |
| Elevation.dxf | A 数值直接读取 | 读 DXF 里的文字 | width_mm = 4480 · High 高 · A-ANNO · (0, 3000)<br>height_mm = 2560 · High 高 · A-ANNO · (0, 3000)<br>pixel_pitch_mm = 2.5 · High 高 · A-ANNO · (0, 2700)<br>environment = indoor · Medium 中（须确认） · A-ANNO · (0, 2700) |
| LED_Requirement.xlsx | A 数值直接读取 | 按栏名匹配 | environment = indoor · High 高 · LED!B4<br>pixel_pitch_mm = 2.5 · High 高 · LED!B6<br>installation = wall · High 高 · LED!B9<br>maintenance = front · High 高 · LED!B10<br>brightness_required_nits = 600 · High 高 · LED!B11 |
| Lobby_Elevation_RevB.pdf | A 数值直接读取 | 文本层，直接读取 | width_mm = 4500 · High 高 · p.2<br>height_mm = 2560 · High 高 · p.2<br>pixel_pitch_mm = 2.5 · High 高 · p.2<br>environment = indoor · Medium 中（须确认） · p.2 |
| Lobby_site_photo.jpg | B 文字识别，须逐项确认 | 先文字识别，再读尺寸 | width_mm = 4480 · Medium 中（须确认） · 文字识别<br>height_mm = 2560 · Medium 中（须确认） · 文字识别<br>viewing_distance_m = [4, 6] · Medium 中（须确认） · 文字识别 |
| Scanned_Plan.pdf | B 文字识别，须逐项确认 | 先文字识别，再读尺寸 | width_mm = 4480 · Low 低（须确认） · p.1 · 文字识别<br>height_mm = 2560 · Low 低（须确认） · p.1 · 文字识别 |
