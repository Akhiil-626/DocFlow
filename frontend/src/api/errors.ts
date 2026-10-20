export interface ApiError {
  status: number;
  message: string;
  fieldErrors?: Record<string, string>;
}

export function parseApiError(error: unknown, status?: number): ApiError {
  if (!navigator.onLine) {
    return {
      status: 0,
      message: 'Cannot reach the server. Please check your internet connection.',
    };
  }

  if (error instanceof TypeError && error.message.includes('fetch')) {
    return {
      status: 0,
      message: 'Cannot reach the server. Please ensure the backend is running.',
    };
  }

  const errObj = error as { detail?: unknown; message?: string } | undefined;

  let message = 'An unexpected error occurred.';
  const fieldErrors: Record<string, string> = {};

  if (errObj && errObj.detail) {
    if (typeof errObj.detail === 'string') {
      message = errObj.detail;
    } else if (Array.isArray(errObj.detail)) {
      // FastAPI 422 validation errors: [{ loc: ['body', 'field'], msg: 'error' }]
      const messages: string[] = [];
      for (const item of errObj.detail) {
        if (typeof item === 'object' && item !== null) {
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : '';
          const msg = item.msg || 'Invalid value';
          const field = Array.isArray(item.loc) && item.loc.length > 1 ? String(item.loc[item.loc.length - 1]) : '';
          if (field) {
            fieldErrors[field] = msg;
          }
          messages.push(loc ? `${field || loc}: ${msg}` : msg);
        }
      }
      if (messages.length > 0) {
        message = messages.join('; ');
      }
    }
  } else if (errObj && typeof errObj.message === 'string') {
    message = errObj.message;
  } else if (status) {
    switch (status) {
      case 400:
        message = 'Bad request.';
        break;
      case 401:
        message = 'Invalid credentials or session expired.';
        break;
      case 403:
        message = 'You do not have permission to perform this action.';
        break;
      case 404:
        message = 'The requested resource was not found.';
        break;
      case 409:
        message = 'A conflict occurred with the current state of the resource.';
        break;
      case 422:
        message = 'Validation failed. Please check your inputs.';
        break;
      case 500:
        message = 'Internal server error. Please try again later.';
        break;
      default:
        message = `Request failed with status ${status}.`;
    }
  }

  return {
    status: status || 0,
    message,
    fieldErrors: Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined,
  };
}
