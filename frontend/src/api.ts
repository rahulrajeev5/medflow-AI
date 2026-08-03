export type ApiDocumentStatus =
  | 'UPLOADED'
  | 'PROCESSING'
  | 'COMPLETED'
  | 'FAILED';

export type ApiDocument = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: ApiDocumentStatus;
  document_type: string | null;
  ocr_text?: string | null;
  ai_summary?: string | null;
  structured_data?: Record<string, unknown> | null;
  error_message?: string | null;
  processing_time_ms: number | null;
  created_at: string;
  updated_at?: string;
};

const API_BASE =
  'https://m0s6u27exj.execute-api.eu-central-1.amazonaws.com/api/v1';

let accessToken: string | null = null;

export function setAccessToken(
  token: string | null,
): void {
  accessToken = token;
}

function getAuthHeaders(): Record<string, string> {
  if (!accessToken) {
    return {};
  }

  return {
    Authorization: `Bearer ${accessToken}`,
  };
}

export async function listDocuments(): Promise<ApiDocument[]> {
  const response = await fetch(
    `${API_BASE}/documents`,
    {
      headers: {
        ...getAuthHeaders(),
      },
    },
  );

  if (!response.ok) {
    throw new Error(
      `Unable to load documents. Status: ${response.status}`,
    );
  }

  return response.json();
}

export async function uploadDocument(
  file: File,
): Promise<ApiDocument> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(
    `${API_BASE}/documents`,
    {
      method: 'POST',
      headers: {
        ...getAuthHeaders(),
      },
      body: formData,
    },
  );

  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => null);

    throw new Error(
      body?.detail ??
        `Upload failed. Status: ${response.status}`,
    );
  }

  return response.json();
}

export async function getDocument(
  id: string,
): Promise<ApiDocument> {
  const response = await fetch(
    `${API_BASE}/documents/${id}`,
    {
      headers: {
        ...getAuthHeaders(),
      },
    },
  );

  if (!response.ok) {
    throw new Error(
      `Unable to load document. Status: ${response.status}`,
    );
  }

  return response.json();
}