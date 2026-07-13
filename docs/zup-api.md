# 1C ZUP Employee Search

The supplied `API 1С ЗУБ ( Информация о сотрудниках ) (1).xlsx` file describes the 1C ZUP API contract rather than employee records. The protected search feature uses that contract without importing personal data into Qdrant or the RAG corpus.

## Access Model

- `admin` can assign the `superuser` role in the Users tab.
- `superuser` can search 1C ZUP but cannot manage users, documents, or system settings.
- Every 1C query is recorded in `admin_audit_logs` with an HMAC query fingerprint and result count. The raw query and employee response are not written to the audit table.

## Configuration

Configure the existing 1C ZUP endpoint in `.env`:

```dotenv
ZUP_API_BASE_URL=https://zup.example.internal/api
ZUP_EMPLOYEES_PATH=/employees
ZUP_SEARCH_PARAM=q
ZUP_API_TOKEN=replace-with-1c-api-token
ZUP_AUTH_HEADER=Authorization
```

`zup-service` sends `GET {ZUP_API_BASE_URL}{ZUP_EMPLOYEES_PATH}` with the configured search parameter and a `limit` parameter. It accepts common response wrappers: `data`, `value`, `items`, `results`, and `employees`.

Adapt `ZUP_EMPLOYEES_PATH` and `ZUP_SEARCH_PARAM` to the actual published 1C HTTP/OData interface. The workbook alone does not specify an endpoint URL, authentication scheme, or response envelope.

## Supported Employee Fields

The proxy returns only documented employee fields, including `pinfl`, `id_pers`, `name`, `tab_num`, organisation and department codes, profession, grade, gender, address, date of birth, passport number, education, speciality and dismissal status.

For sensitive deployments, configure the upstream API to return only the fields necessary for lookup and use HTTPS between the application and 1C.
