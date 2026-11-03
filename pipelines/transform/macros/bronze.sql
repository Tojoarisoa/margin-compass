{# Reads one source file from the bronze partition written by ingest for this run. #}
{% macro bronze(source_file) -%}
read_parquet('{{ var("bronze_path") }}/{{ source_file.split("/")[0] }}/ingest_date={{ var("ingest_date") }}/{{ source_file.split("/")[1] }}')
{%- endmacro %}
