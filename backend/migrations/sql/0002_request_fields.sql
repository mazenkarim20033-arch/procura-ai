-- Purchase request intake: names as written, source document, fingerprint index, request numbers.
alter table public.purchase_requests
  add column requester_name varchar(255),
  add column supplier_name varchar(255),
  add column source_document_id uuid;

alter table public.purchase_requests
  add constraint fk_purchase_requests_source_document_id_documents
  foreign key (source_document_id) references public.documents (id);

create index ix_purchase_requests_fingerprint on public.purchase_requests (fingerprint);

-- Generated request numbers: PR-<year>-<sequence>.
create sequence if not exists public.request_no_seq;
