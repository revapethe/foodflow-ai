"""Optional PySpark exploration. Requires Java 17 and requirements-spark.txt."""
from pyspark.sql import SparkSession,functions as F
from .config import RAW

def main():
    spark=SparkSession.builder.master('local[*]').appName('FoodFlowLocal').getOrCreate()
    try:
        orders=spark.read.option('header',True).option('inferSchema',True).csv(str(RAW/'orders.csv'))
        orders.filter(F.col('status')=='delivered').groupBy('restaurant_id').agg(F.round(F.sum('order_total'),2).alias('revenue')).orderBy(F.desc('revenue')).show(10)
    finally: spark.stop()
if __name__=='__main__': main()
