from sec_api import QueryApi

queryApi = QueryApi(api_key="YOUR_API_KEY")

query = {
  "query": { "query_string": {
      "query": "formType:\"13F\" AND filedAt:{2025-01-01 TO 2025-01-31}"
    }},
  "from": "0",
  "size": "100",
  "sort": [{ "filedAt": { "order": "desc" }}]
}
filings = queryApi.get_filings(query)