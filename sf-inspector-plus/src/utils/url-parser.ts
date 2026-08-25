export interface ParsedRecordUrl {
  objectName: string;
  recordId: string;
}

export function parseRecordUrl(url: string): ParsedRecordUrl | null {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname;

    const lightningMatch = path.match(
      /\/lightning\/r\/([A-Za-z_][A-Za-z0-9_]*)\/([a-zA-Z0-9]{15,18})\/view/
    );
    if (lightningMatch) {
      return { objectName: lightningMatch[1], recordId: lightningMatch[2] };
    }

    const classicIdParam = parsed.searchParams.get('id');
    if (classicIdParam && /^[a-zA-Z0-9]{15,18}$/.test(classicIdParam)) {
      return { objectName: '', recordId: classicIdParam };
    }

    const classicPathMatch = path.match(/\/([a-zA-Z0-9]{15,18})$/);
    if (classicPathMatch) {
      return { objectName: '', recordId: classicPathMatch[1] };
    }

    return null;
  } catch {
    return null;
  }
}

export function getKeyPrefix(recordId: string): string {
  return recordId.substring(0, 3);
}
