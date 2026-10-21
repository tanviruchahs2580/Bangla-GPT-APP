# Profiler evidence (I-07 / AUD-HI-11)

- date: 2026-10-19T09:39:58.656003+00:00
- python: 3.12.10 on win32
- command: `python scripts/profile_report.py --iterations 60 --top 20`
- provider: mock (no network); corpus: bundled sample (78 chunks);
  database: SQLite file (the local default)
- tutor ask: 60 calls, 1.181s wall, 19.68 ms/call
- dashboard: 60 calls, 0.61s wall, 10.17 ms/call (cache cleared each call: this is the uncached fan-out)

`cProfile` (stdlib) with `pstats`; py-spy is not installed in this
environment. Per path the archive holds two rankings: cumulative time
(what the request waits in) and self time (the CPU hot list -- the one to
read when the machine is shared with other work).

## Top functions by self time

```text
   0.2076s self     0.4369s cum  hybrid.py:111(light_stem)
   0.1898s self     0.1898s cum  ~:0(<method 'endswith' of 'str' objects>)
   0.0862s self     0.0862s cum  ~:0(<method 'translate' of 'str' objects>)
   0.0664s self     0.2006s cum  hybrid.py:39(tokenize)
   0.0528s self     0.0528s cum  ~:0(<method 'search' of 're.Pattern' objects>)
   0.0313s self     0.0313s cum  ~:0(<built-in method unicodedata.normalize>)
   0.0252s self     0.4824s cum  safety.py:124(verify_citation)
   0.0216s self     0.0216s cum  ~:0(<method 'lower' of 'str' objects>)
   0.0206s self     0.0430s cum  copy.py:118(deepcopy)
   0.0196s self     0.0320s cum  thread.py:165(submit)
   0.0193s self     0.0488s cum  hybrid.py:147(trigram_ngrams)
   0.0175s self     0.0175s cum  ~:0(<method 'group' of 're.Match' objects>)
   0.0130s self     0.0130s cum  ~:0(<built-in method builtins.len>)
   0.0126s self     0.2617s cum  tutor.py:676(_coverage_details)
   0.0104s self     0.0104s cum  ~:0(<method 'sub' of 're.Pattern' objects>)
   0.0091s self     0.0091s cum  ~:0(<method 'send' of '_socket.socket' objects>)
   0.0088s self     0.0298s cum  logging_config.py:89(redact_value)
   0.0083s self     0.0083s cum  ~:0(<method 'validate_python' of 'pydantic_core._pydantic_core.SchemaValidator' objects>)
   0.0080s self     0.0393s cum  copy.py:217(_deepcopy_dict)
   0.0080s self     0.0080s cum  ~:0(<built-in method _overlapped.GetQueuedCompletionStatus>)
--- dashboard ---
   0.0339s self     0.0957s cum  coercions.py:323(expect)
   0.0265s self     0.0265s cum  ~:0(<method 'execute' of 'sqlite3.Cursor' objects>)
   0.0235s self     0.0395s cum  cache_key.py:209(_generate_cache_key)
   0.0189s self     0.0201s cum  ~:0(<method 'get' of 'dict' objects>)
   0.0175s self     0.0419s cum  default.py:1564(_init_compiled)
   0.0167s self     0.0421s cum  copy.py:118(deepcopy)
   0.0162s self     0.0467s cum  loading.py:80(instances)
   0.0137s self     0.0186s cum  langhelpers.py:1446(__get__)
   0.0137s self     0.5460s cum  learn.py:641(_build_dashboard_summary)
   0.0097s self     0.2841s cum  session.py:2201(_execute_internal)
   0.0090s self     0.0129s cum  loading.py:819(_instance_processor)
   0.0087s self     0.1836s cum  base.py:1621(_execute_clauseelement)
   0.0079s self     0.0407s cum  copy.py:217(_deepcopy_dict)
   0.0078s self     0.0177s cum  elements.py:4249(__init__)
   0.0074s self     0.0077s cum  ~:0(<built-in method builtins.isinstance>)
   0.0072s self     0.0072s cum  ~:0(<method 'validate_python' of 'pydantic_core._pydantic_core.SchemaValidator' objects>)
   0.0072s self     0.0079s cum  ~:0(<method 'sub' of 're.Pattern' objects>)
   0.0071s self     0.0268s cum  elements.py:2060(__init__)
   0.0071s self     0.0071s cum  ~:0(<method 'fetchall' of 'sqlite3.Cursor' objects>)
   0.0070s self     0.0245s cum  default.py:2104(_setup_result_proxy)
```

## TutorService.ask

### by cumulative time

```text
         595952 function calls (588900 primitive calls) in 1.179 seconds

   Ordered by: cumulative time
   List reduced from 658 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
      128    0.005    0.000    3.029    0.024 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py:1922(_run_once)
      254    0.001    0.000    2.351    0.009 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py:86(_run)
      254    0.007    0.000    2.349    0.009 {method 'run' of '_contextvars.Context' objects}
        3    0.000    0.000    1.491    0.497 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py:655(run_until_complete)
        3    0.000    0.000    1.491    0.497 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py:318(run_forever)
        3    0.000    0.000    1.490    0.497 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py:631(run_forever)
        1    0.000    0.000    1.180    1.180 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py:160(run)
        1    0.000    0.000    1.178    1.178 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py:61(__exit__)
        1    0.000    0.000    1.178    1.178 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py:64(close)
        2    0.000    0.000    1.176    0.588 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py:590(shutdown_default_executor)
      120    0.007    0.000    1.053    0.009 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\tutor.py:1327(ask)
       61    0.001    0.000    1.026    0.017 C:\Users\DST\projects\Bangla GPT APP\apps\api\scripts\profile_report.py:90(run)
        4    0.000    0.000    0.968    0.242 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\threading.py:1117(join)
    99/85    0.004    0.000    0.657    0.008 {method 'acquire' of '_thread.lock' objects}
        4    0.000    0.000    0.654    0.163 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\threading.py:1155(_wait_for_tstate_lock)
        2    0.000    0.000    0.646    0.323 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\concurrent\futures\thread.py:220(shutdown)
      120    0.005    0.000    0.528    0.004 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\tutor.py:1230(_post_check)
      120    0.025    0.000    0.482    0.004 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\safety.py:124(verify_citation)
    20184    0.208    0.000    0.437    0.000 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\retrieval\hybrid.py:111(light_stem)
       60    0.004    0.000    0.319    0.005 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\tutor.py:1265(_assemble)

```

### by self time (CPU hot list)

```text
         595952 function calls (588900 primitive calls) in 1.179 seconds

   Ordered by: internal time
   List reduced from 658 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
    20184    0.208    0.000    0.437    0.000 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\retrieval\hybrid.py:111(light_stem)
   315455    0.190    0.000    0.190    0.000 {method 'endswith' of 'str' objects}
    21627    0.086    0.000    0.086    0.000 {method 'translate' of 'str' objects}
      489    0.066    0.000    0.201    0.000 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\retrieval\hybrid.py:39(tokenize)
    25623    0.053    0.000    0.053    0.000 {method 'search' of 're.Pattern' objects}
      549    0.031    0.000    0.031    0.000 {built-in method unicodedata.normalize}
      120    0.025    0.000    0.482    0.004 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\safety.py:124(verify_citation)
    24107    0.022    0.000    0.022    0.000 {method 'lower' of 'str' objects}
  6000/60    0.021    0.000    0.043    0.001 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\copy.py:118(deepcopy)
       60    0.020    0.000    0.032    0.001 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\concurrent\futures\thread.py:165(submit)
     2655    0.019    0.000    0.049    0.000 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\retrieval\hybrid.py:147(trigram_ngrams)
    21327    0.018    0.000    0.018    0.000 {method 'group' of 're.Match' objects}
30424/30390    0.013    0.000    0.013    0.000 {built-in method builtins.len}
       60    0.013    0.000    0.262    0.004 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\tutor.py:676(_coverage_details)
     4160    0.010    0.000    0.010    0.000 {method 'sub' of 're.Pattern' objects}
       61    0.009    0.000    0.009    0.000 {method 'send' of '_socket.socket' objects}
  840/240    0.009    0.000    0.030    0.000 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\logging_config.py:89(redact_value)
      417    0.008    0.000    0.008    0.000 {method 'validate_python' of 'pydantic_core._pydantic_core.SchemaValidator' objects}
  540/180    0.008    0.000    0.039    0.000 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\copy.py:217(_deepcopy_dict)
      193    0.008    0.000    0.008    0.000 {built-in method _overlapped.GetQueuedCompletionStatus}

```

## GET /dashboard/summary

### by cumulative time

```text
         102923 function calls (96829 primitive calls) in 0.610 seconds

   Ordered by: cumulative time
   List reduced from 532 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.001    0.001    0.610    0.610 C:\Users\DST\projects\Bangla GPT APP\apps\api\scripts\profile_report.py:148(run)
       60    0.004    0.000    0.608    0.010 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\routers\learn.py:615(dashboard_summary)
       60    0.014    0.000    0.546    0.009 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\routers\learn.py:641(_build_dashboard_summary)
      240    0.001    0.000    0.286    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\session.py:2406(execute)
      240    0.010    0.000    0.284    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\session.py:2201(_execute_internal)
      240    0.005    0.000    0.250    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\context.py:306(orm_execute_statement)
       60    0.000    0.000    0.188    0.003 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\weakness.py:103(weak_names)
       60    0.001    0.000    0.188    0.003 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\weakness.py:98(weak_concepts)
      240    0.002    0.000    0.187    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\base.py:1407(execute)
       60    0.005    0.000    0.186    0.003 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\services\weakness.py:58(raw_cells)
      240    0.001    0.000    0.185    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\elements.py:524(_execute_on_connection)
      240    0.009    0.000    0.184    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\base.py:1621(_execute_clauseelement)
       60    0.007    0.000    0.121    0.002 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\routers\deps.py:388(_build_me_response)
      360    0.001    0.000    0.114    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\attributes.py:456(operate)
      360    0.001    0.000    0.109    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\properties.py:481(operate)
      240    0.006    0.000    0.106    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\base.py:1770(_execute_context)
      360    0.001    0.000    0.104    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\elements.py:1592(operate)
      360    0.003    0.000    0.101    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\type_api.py:261(operate)
     1464    0.034    0.000    0.096    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\coercions.py:323(expect)
 1200/300    0.004    0.000    0.084    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\operators.py:741(__eq__)

```

### by self time (CPU hot list)

```text
         102923 function calls (96829 primitive calls) in 0.610 seconds

   Ordered by: internal time
   List reduced from 532 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
     1464    0.034    0.000    0.096    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\coercions.py:323(expect)
      240    0.026    0.000    0.026    0.000 {method 'execute' of 'sqlite3.Cursor' objects}
      240    0.023    0.000    0.040    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\cache_key.py:209(_generate_cache_key)
    12240    0.019    0.000    0.020    0.000 {method 'get' of 'dict' objects}
      240    0.017    0.000    0.042    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\default.py:1564(_init_compiled)
  3840/60    0.017    0.000    0.042    0.001 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\copy.py:118(deepcopy)
      240    0.016    0.000    0.047    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\loading.py:80(instances)
       60    0.014    0.000    0.546    0.009 C:\Users\DST\projects\Bangla GPT APP\apps\api\src\bangla_gpt_api\routers\learn.py:641(_build_dashboard_summary)
  637/631    0.014    0.000    0.019    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\util\langhelpers.py:1446(__get__)
      240    0.010    0.000    0.284    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\session.py:2201(_execute_internal)
      180    0.009    0.000    0.013    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\orm\loading.py:819(_instance_processor)
      240    0.009    0.000    0.184    0.001 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\base.py:1621(_execute_clauseelement)
   420/60    0.008    0.000    0.041    0.001 C:\Users\DST\AppData\Local\Programs\Python\Python312\Lib\copy.py:217(_deepcopy_dict)
      360    0.008    0.000    0.018    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\elements.py:4249(__init__)
     5866    0.007    0.000    0.008    0.000 {built-in method builtins.isinstance}
      363    0.007    0.000    0.008    0.000 {method 'sub' of 're.Pattern' objects}
      420    0.007    0.000    0.007    0.000 {method 'validate_python' of 'pydantic_core._pydantic_core.SchemaValidator' objects}
      240    0.007    0.000    0.007    0.000 {method 'fetchall' of 'sqlite3.Cursor' objects}
      300    0.007    0.000    0.027    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\sql\elements.py:2060(__init__)
      240    0.007    0.000    0.025    0.000 C:\Users\DST\projects\Bangla GPT APP\.venv\Lib\site-packages\sqlalchemy\engine\default.py:2104(_setup_result_proxy)

```
