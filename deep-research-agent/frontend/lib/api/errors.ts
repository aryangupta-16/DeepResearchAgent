/**
 * API error raised when a request fails. Mirrors the backend's
 * {@class app.common.exceptions.AppError} hierarchy.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const STATUS_MESSAGE: Record<number, string> = {
  400: "Bad request",
  404: "Resource not found",
  409: "Conflict",
  422: "Validation failed",
  500: "Internal server error",
};

/**
 * Parse a non-2xx fetch response into an {@link ApiError}.
 * The backend returns JSON errors like `{"detail": "..."}` / `{"detail":[{"loc":...,"msg":...}]}`.
 */
export async function parseApiError(response: Response): Promise<ApiError> {
  let message: string;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body.detail)) {
      // pydantic 422 shape: [{ loc, msg, type }]
      message = body.detail
        .map((d: { msg?: string }) => d?.msg || "validation error")
        .join("; ");
    } else {
      message = JSON.stringify(body);
    }
  } catch {
    message = STATUS_MESSAGE[response.status] || `Error ${response.status}`;
  }
    return new ApiError(
    response.status,
    message || STATUS_MESSAGE[response.status] || response.statusText,
  );
}
