from pyspark import rdd
from pyspark.sql import SparkSession
from pyspark.sql.types import IntegerType, StructType, StringType, StructField, ArrayType


def prefix_find(data: str, prefix: str, n: int) -> str:
    idx = data.find(prefix)
    if idx >= 0:
        start = idx + len(prefix)
        if n <= 0:
            return data[start:]
        return data[start: start + n]
    return ""


def range_find(data: str, prefix: str, suffix: str) -> str:
    start_index = data.find(prefix)
    end_index = data.find(suffix)
    if start_index < 0 or start_index >= end_index:
        return ""

    # Extract the JSON string from this point
    return data[start_index + len(prefix): end_index]


import json


def json_list(data: str) -> list:
    if len(data) == 0:
        return []
    try:
        a = json.loads(data)
    except json.JSONDecodeError:
        return []
    return a


def extract_dialogue_states(log_data: rdd) -> tuple:
    data = log_data["value"]
    if not isinstance(data, str):
        return ()

    reg_ = prefix_find(data, 'Region:', 2)
    s_id = prefix_find(data, 'session=', len('1209602234582438784'))
    node = range_find(data, 'reply=', ',buttons=')
    buttons = json_list(range_find(data, 'buttons=', ',conditions='))
    c_lis = json_list(range_find(data,'conditions=', ',rounds='))
    r_lis = json_list(prefix_find(data, 'rounds=', -1))
    i_id = range_find(data, 'instance=', ',session')
    t_id = prefix_find(data, 'TraceId:', len('5134483e108512de5f96bada924e1a02'))
    dt = log_data["dt"]

    return (reg_,
            s_id,
            node,
            buttons,
            c_lis,
            r_lis,
            i_id,
            t_id,
            dt)


def process(schema: str):
    spark = SparkSession.builder.appName("chatbot.tfe.taskbot.dst").enableHiveSupport().getOrCreate()
    df = spark.sql('''select * from {0}.log_data_taskbot_reply__reg_continuous_s0_live where from_unixtime(
    _timestamp, 'yyyy-MM-dd') = date_sub(current_timestamp(), 1)'''.format(schema))

    target_schema = StructType([
        StructField("region", StringType()),
        StructField("session_id", StringType()),
        StructField("node_content", StringType(), True),
        StructField("buttons", ArrayType(StringType()), True),
        StructField("condition_list", ArrayType(StringType()), True),
        StructField("session_rounds", ArrayType(StructType([
            StructField("utterance", StringType(), True),
            StructField("create_method", StringType(), True),
            StructField("answer_list", ArrayType(StringType())),
        ])
        )),
        StructField("instance_id", StringType(), True),  # component service instance id
        StructField("trace_id", StringType()),
        StructField("create_time", StringType())
    ])

    target_rdd = df.rdd.map(extract_dialogue_states)
    result = target_rdd.toDF(schema=target_schema)

    target_hive_tab = "{0}.shopee_tfe_dwd_taskbot_llm_dataset_df__reg_live".format(schema)

    result.write. \
        mode("append"). \
        partitionBy("region"). \
        saveAsTable(target_hive_tab)

    spark.stop()