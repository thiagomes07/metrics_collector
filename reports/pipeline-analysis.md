# Relatório técnico do experimento CI/CD

<a id="escopo-e-origem"></a>
## Escopo e origem

Este repositório adapta o projeto real [python-humanize/humanize](https://github.com/python-humanize/humanize), clonado no commit `d333afdc5e05941c67c552c9f153eec4d48e64b4`. A escolha foi deliberada: a biblioteca tem testes sobre formatação de número, tamanho, listas, datas e internacionalização, então o pipeline mede trabalho real de Python em vez de um exercício vazio.

Os artefatos locais incluem workflow, coletor, CSV de exemplo, gerador de gráficos e este relatório. O arquivo `data/sample_pipeline_metrics.csv` é sintético e serve para validar a estrutura. Eu não marquei IDs, links ou prints sintéticos como evidência real. Para a entrega acadêmica final, rode o workflow 12 vezes no seu repositório GitHub e gere `data/pipeline_metrics.csv` com `scripts/collect_metrics.py`.

<a id="estrutura"></a>
## Estrutura de diretórios

```text
.github/workflows/pipeline-metrics.yml
scripts/ci_variation_tests.py
scripts/summarize_junit.py
scripts/collect_metrics.py
scripts/generate_charts.py
requirements-experiment.txt
data/sample_pipeline_metrics.csv
data/sample_step_metrics.csv
charts/
reports/pipeline-analysis.md
```

<a id="pipeline"></a>
## Pipeline

O workflow `CI Metrics Experiment` cobre instalação de dependências, cache de `pip`, lint com `ruff`, testes com `pytest`, artifacts de resultado e um job final de snapshot. Ele usa `workflow_dispatch`, `matrix`, `needs`, `actions/cache` e `actions/upload-artifact`.

Arquivo YAML: `.github/workflows/pipeline-metrics.yml`

Jobs:

- `quality gate`: instala dependências, roda `ruff check src tests`, salva `quality-summary.json`.
- `tests (3.11)` e `tests (3.12)`: rodam em matrix, geram variações controladas e publicam JUnit, log do pytest e `summary.json`.
- `tests sequential (3.12)`: usado quando `execution_mode=sequential`.
- `metrics snapshot`: consolida contexto do run e status dos jobs via `needs`.

<a id="variacoes"></a>
## Variações planejadas

As 12 execuções devem ser disparadas por `workflow_dispatch`, cada uma com uma hipótese operacional clara:

| Execução | `experiment_variant` | Parâmetros principais | Justificativa |
|---:|---|---|---|
| 1 | `baseline` | cache on, parallel, 0 extras | Medir referência limpa. |
| 2 | `repeat-baseline` | cache on, parallel, 0 extras | Separar ruído de runner de mudança real. |
| 3 | `cache-disabled` | cache off | Medir custo de instalação sem cache. |
| 4 | `cache-restored` | cache on | Confirmar recuperação depois do cache frio. |
| 5 | `extra-tests-40` | 40 testes gerados | Observar crescimento moderado da suíte. |
| 6 | `extra-tests-120` | 120 testes gerados | Forçar pressão maior sem alterar a aplicação. |
| 7 | `slow-test-2s` | `slow_test_seconds=2` | Simular I/O lento isolado. |
| 8 | `slow-test-5s` | `slow_test_seconds=5` | Medir amplificação do teste lento na matrix. |
| 9 | `forced-failure` | `fail_mode=generated-assertion` | Coletar status e artifacts em pipeline vermelho. |
| 10 | `sequential-tests` | `execution_mode=sequential` | Comparar contra execução paralela. |
| 11 | `parallel-tests` | `execution_mode=parallel` | Repetir paralelismo após sequential para reduzir efeito temporal. |
| 12 | `cache-bust` | `cache_mode=bust` | Medir custo de chave nova sem desligar a lógica de cache. |

Com GitHub CLI, o formato dos disparos é:

```bash
gh workflow run pipeline-metrics.yml -f experiment_variant=baseline -f execution_mode=parallel -f cache_mode=on -f extra_test_cases=0 -f slow_test_seconds=0 -f fail_mode=none
gh workflow run pipeline-metrics.yml -f experiment_variant=cache-disabled -f execution_mode=parallel -f cache_mode=off -f extra_test_cases=0 -f slow_test_seconds=0 -f fail_mode=none
gh workflow run pipeline-metrics.yml -f experiment_variant=extra-tests-120 -f execution_mode=parallel -f cache_mode=on -f extra_test_cases=120 -f slow_test_seconds=0 -f fail_mode=none
gh workflow run pipeline-metrics.yml -f experiment_variant=forced-failure -f execution_mode=parallel -f cache_mode=on -f extra_test_cases=0 -f slow_test_seconds=0 -f fail_mode=generated-assertion
```

<a id="coleta"></a>
## Coleta de métricas

O coletor usa a API REST do GitHub com autenticação por token. Ele pagina workflow runs e jobs, respeita rate limit, baixa artifacts do run, lê JUnit/JSON e grava duas bases:

- `data/pipeline_metrics.csv`: linha por job, com `run_id`, commit, status, duração do workflow, duração do job, contagem de testes e campos extras.
- `data/step_metrics.csv`: linha por etapa do job, com duração de steps relevantes.

Comando:

```bash
GITHUB_TOKEN=ghp_xxx python scripts/collect_metrics.py \
  --repo SEU_USUARIO/metrics_collector \
  --workflow pipeline-metrics.yml \
  --limit 12 \
  --out data/pipeline_metrics.csv \
  --steps-out data/step_metrics.csv \
  --artifacts-dir data/downloaded-artifacts
```

Campos extras incluídos: `run_attempt`, `event`, `branch`, `variant`, `python_version`, `lead_time_seconds`, `artifact_count` e `html_url`. Eles reduzem ambiguidade quando um run é reexecutado, quando a branch muda ou quando a matrix mistura versões de Python.

<a id="graficos"></a>
## Gráficos

O script de visualização gera cinco PNGs:

- `charts/pipeline_duration_by_run.png`
- `charts/job_duration_by_job.png`
- `charts/success_failure_rate.png`
- `charts/tests_vs_duration.png`
- `charts/step_duration_by_step.png`

Comando:

```bash
python scripts/generate_charts.py \
  --metrics data/pipeline_metrics.csv \
  --steps data/step_metrics.csv \
  --out-dir charts
```

Para validar localmente antes das execuções reais:

```bash
python scripts/generate_charts.py \
  --metrics data/sample_pipeline_metrics.csv \
  --steps data/sample_step_metrics.csv \
  --out-dir charts
```

<a id="leitura-dos-dados-de-exemplo"></a>
## Leitura dos dados de exemplo

A análise abaixo usa `data/sample_pipeline_metrics.csv`. Ela é útil para revisar o método, mas não substitui os runs reais exigidos pela atividade.

| Métrica | Valor no exemplo |
|---|---:|
| Execuções | 12 |
| Sucessos | 11 |
| Falhas | 1 |
| Menor duração | 72 s (`forced-failure`) |
| Maior duração | 146 s (`sequential-tests`) |
| Baseline médio | 86 s |
| Cache desligado | 122 s |
| Cache restaurado | 80 s |
| Paralelo após sequential | 91 s |

<a id="perguntas-de-analise"></a>
## Perguntas de análise

**Qual etapa mais contribuiu para o tempo total do pipeline?**  
Nos dados de exemplo, `Run pytest` domina o tempo de job. A média do step de pytest nos 12 runs representativos ficou acima de 60 s, enquanto `Lint source and tests` ficou estável em 4 s. No nível de job, os jobs `tests (3.11)` e `tests (3.12)` são consistentemente maiores que `quality gate`.

**Houve diferença significativa entre execuções com e sem cache?**  
Sim no exemplo. `cache-disabled` levou 122 s, contra 80 s em `cache-restored` e média de 86 s nos dois baselines. A diferença prática foi de 36 s a 42 s, concentrada no step `Install dependencies`.

**O paralelismo reduziu o tempo total? Em que condições?**  
Reduziu quando havia dois jobs de teste independentes. `sequential-tests` levou 146 s; `parallel-tests`, executado logo depois, levou 91 s. A redução foi de 55 s, cerca de 38%. O ganho depende do teste caber bem em jobs independentes e do runner não sofrer fila longa.

**Quais falhas foram mais frequentes?**  
O exemplo tem uma única falha planejada: `forced-failure`, causada por `fail_mode=generated-assertion`. Como a matrix roda em Python 3.11 e 3.12, o mesmo defeito aparece em dois jobs, mas representa uma falha lógica única.

**O pipeline fornece feedback rápido o suficiente para o desenvolvedor?**  
Na baseline, sim: 84 s a 88 s é aceitável para pull request pequeno. A resposta muda nas variações: sem cache, com 120 testes extras, com teste lento de 5 s e em modo sequencial, o feedback passa de 2 min. Para uma equipe que faz commits pequenos, eu trataria 90 s como alvo e 120 s como limite de investigação.

**Que melhorias poderiam ser feitas no pipeline?**  
Eu manteria cache obrigatório para `pip`, separaria testes lentos por marcador, adicionaria limite de duração por teste com `pytest-timeout`, preservaria o JUnit por job e passaria a publicar um resumo Markdown no job final. Para custo, eu evitaria matrix completa em todo push se a mudança tocar apenas documentação.

**Quais limitações existem nos dados coletados?**  
A duração do workflow mistura execução com overhead do GitHub Actions. O Jobs API não expõe diretamente o output `cache-hit`, então o pipeline grava esse valor em artifact e o coletor tenta recuperá-lo dali. Artifacts expiram, então a coleta tardia pode perder JUnit. A contagem de testes soma a matrix; quando o mesmo teste roda em duas versões de Python, ele aparece duas vezes por desenho experimental.

**Como essa análise poderia apoiar decisões de engenharia?**  
Ela separa custo fixo de setup, custo variável da suíte e custo de paralelismo. Com isso dá para justificar cache, decidir se vale dividir testes por marcador, definir alvo de tempo para PR e priorizar otimização de testes lentos com impacto real em feedback.

<a id="resultados-inesperados"></a>
## Resultados inesperados

O primeiro resultado contraintuitivo no exemplo é `forced-failure` ser o run mais curto, com 72 s. Eu esperaria uma falha planejada custar quase o mesmo que baseline, já que o pytest não foi configurado com `-x`. A explicação provável é combinação de cache quente, menor variação de instalação e encerramento mais barato no pós-processamento. Em dados reais, eu conferiria os steps para validar se a economia veio de execução de teste ou de setup.

O segundo resultado estranho é `slow-test-5s` custar 134 s. A diferença contra `slow-test-2s` foi de 33 s, maior que os 6 s esperados para duas versões de Python. Isso sugere que o atraso artificial não foi o único fator; o runner pode ter ficado mais lento, a instalação pode ter variado, ou o teste lento pode ter deslocado o caminho crítico da matrix.

<a id="hipotese-vs-resultado"></a>
## Hipótese inicial vs resultado observado

Minha hipótese inicial era que o cache dominaria o tempo total e que aumentar a quantidade de testes teria efeito quase linear. O cache confirmou a hipótese no exemplo: desligar cache adicionou mais de 40 s contra `cache-restored`. A parte dos testes foi menos limpa. `extra-tests-40` subiu para 96 s, mas `extra-tests-120` foi a 128 s; o aumento existe, só que a inclinação não é puramente proporcional porque instalação, scheduler e pós-processamento ainda pesam no caminho crítico.

Sobre paralelismo, a hipótese era redução clara. Ela se confirmou na comparação `sequential-tests` contra `parallel-tests`, mas com uma ressalva: o ganho medido inclui diferença estrutural do job sequencial e ruído temporal. Para fechar a conclusão em dados reais, eu repetiria a dupla sequential/parallel duas vezes.

<a id="evidencias-reais"></a>
## Evidências reais exigidas para entrega

Este arquivo ainda não contém prints nem links reais de GitHub Actions. Depois de executar no seu repositório, preencha esta seção com:

- Link do repositório próprio.
- Link direto para `.github/workflows/pipeline-metrics.yml`.
- 12 links reais de workflow runs.
- IDs reais de `run_id` produzidos por `collect_metrics.py`.
- SHAs reais dos commits ou dos dispatches usados.
- Quatro gráficos gerados a partir de `data/pipeline_metrics.csv`, não do CSV sintético.

Eu prefiro deixar essa ausência explícita a fabricar evidência. A atividade pede execução real, e o próprio valor do experimento depende de ruído, fila, cache e falhas reais do GitHub Actions.

<a id="reproducao"></a>
## Reprodução

1. Crie um repositório próprio no GitHub e envie este projeto.
2. Ative GitHub Actions.
3. Dispare as 12 variações listadas em `Variações planejadas`.
4. Crie um token com permissão de leitura de Actions.
5. Rode `scripts/collect_metrics.py` apontando para o seu `owner/repo`.
6. Rode `scripts/generate_charts.py` usando o CSV real.
7. Substitua a seção `Evidências reais exigidas para entrega` pelos links, IDs e prints verdadeiros.
