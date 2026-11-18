/** RFC 7807 problem+json errors from the backend, with the server's own explanation kept intact. */
export class ApiError extends Error {
  constructor(public status: number, public title: string, public detail: string, public extra?: unknown) {
    super(detail || title);
  }
}
