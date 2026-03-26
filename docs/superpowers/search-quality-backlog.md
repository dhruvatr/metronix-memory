# Search Quality Epic — Backlog

> Доработки и улучшения, выявленные в ходе реализации эпика
> "Investigate and improve search quality to reduce hallucinations".
> Приоритет: после завершения основных задач эпика.

---

## Performance

### P1: Параллельный запуск recall channels
**Проблема:** 4 recall channel'а (dense, exact, metadata, graph) выполняются последовательно — каждый делает отдельный запрос к Qdrant/Memgraph. Общее время поиска выросло с ~8 мин (44 запроса) до ~15 мин (~20с на запрос vs ~11с).
**Решение:** `asyncio.gather(recall_dense, recall_exact, recall_metadata, recall_graph)` — сократит latency этапа recall в 3-4 раза.
**Сложность:** Средняя. Нужен async рефакторинг recall функций в channels.py.
**Источник:** PR #43 code review, замеры eval.

### P2: Уменьшить RERANK_POOL_SIZE
**Проблема:** Cross-encoder обрабатывает 50 кандидатов вместо прежних 25. Удвоение cost inference.
**Решение:** Тюнинг `RERANK_POOL_SIZE` — оценить 30-35 как компромисс. Проверить через eval что качество не падает.
**Сложность:** Низкая. Изменение одного env var + eval-compare.
**Источник:** PR #43 code review, issue #3.

### P3: Кэширование recall_graph
**Проблема:** Memgraph query на каждый поиск — относительно медленный.
**Решение:** LRU cache для graph entity lookup по workspace_id + entity set.
**Сложность:** Низкая.

---

## Quality Tuning

### Q1: Grid search по весам scoring формулы
**Проблема:** Текущие дефолты (dense=0.35, graph=0.15, metadata=0.20, recency=0.10, balance=0.05, blend=0.3) выбраны экспертно, не оптимизированы.
**Решение:** Grid/random search по весам с eval test set как objective function. Оптимизировать по MRR + NDCG@10.
**Сложность:** Низкая технически, нужно время на прогоны.

### Q2: Smooth gradient для source_balance
**Проблема:** Бинарный бонус (0 или 1) на пороге 40% — резкий boundary effect.
**Решение:** `max(0, 1 - count/total/threshold)` — плавный градиент.
**Сложность:** Низкая. Одна функция в scoring.py.
**Источник:** PR #43 code review, issue #4.

### Q3: Negative accuracy = 0%
**Проблема:** Все negative/vague/greeting запросы возвращают 10 документов. Система не умеет отказывать.
**Решение:** Confidence threshold на signal_score — если все кандидаты ниже порога, не отвечать.
**Сложность:** Средняя. Нужен порог + eval для калибровки.

---

## Code Quality

### C1: Очистить _signal_score/_final_score leak в memory dicts
**Проблема:** Internal scores записываются в memory dict объекты (`b["_signal_score"]`, `r["_final_score"]`). Мутация shared dicts.
**Решение:** Отдельный `score_map: dict[str, float]` по chunk_id вместо мутации.
**Сложность:** Низкая.
**Источник:** PR #43 code review, issue #1.

### C2: Кэширование _result_type в scoring loop
**Проблема:** `_result_type()` вызывается дважды на каждый merged result (для Counter и для source_balance).
**Решение:** Вычислить один раз в начале цикла.
**Сложность:** Тривиально.
**Источник:** PR #43 code review, issue #5.

### C3: Убрать dead sparse_weight path
**Проблема:** `sparse_weight=0.0` — channel "sparse" нигде не генерируется, код в compute_signal_score — dead path.
**Решение:** Убрать до появления sparse channel.
**Сложность:** Тривиально.
**Источник:** PR #43 code review, issue #8.

---

## Spec/Doc Updates

### D1: Reconcile spec vs code на нормализацию весов
**Проблема:** Спека говорит "normalized by sum of active weights", код делит на сумму всех весов. Код правильнее — штрафует single-channel results.
**Решение:** Обновить формулировку в спеке.
**Источник:** PR #43 code review, issue #2.
