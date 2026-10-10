/**
 * Cryptographically secure password generation with rejection sampling.
 * Complies with Django's default AUTH_PASSWORD_VALIDATORS:
 * - MinimumLengthValidator (length >= 8, generates 14)
 * - NumericPasswordValidator (guarantees letters and symbols)
 * - CommonPasswordValidator (high-entropy random charset)
 * - UserAttributeSimilarityValidator (similarity check against user details)
 */

const LOWER = "abcdefghjkmnpqrstuvwxyz"; // 23 characters (excluding confusable i, l, o)
const UPPER = "ABCDEFGHJKMNPQRSTUVWXYZ"; // 24 characters (excluding confusable I, O)
const DIGITS = "23456789";               // 8 characters (excluding confusable 0, 1)
const SYMBOLS = "!@#$%*-_+=";            // 10 characters

const ALL_CHARS = LOWER + UPPER + DIGITS + SYMBOLS; // 65 characters

function getCrypto(): Crypto {
  if (typeof window !== "undefined" && window.crypto) {
    return window.crypto;
  }
  if (typeof globalThis !== "undefined" && globalThis.crypto) {
    return globalThis.crypto;
  }
  throw new Error("Cryptographic random number generator is not available.");
}

/**
 * Uniform random integer in [0, maxExclusive) using rejection sampling to eliminate modulo bias.
 */
export function getSecureRandomInt(maxExclusive: number): number {
  if (maxExclusive <= 0 || maxExclusive > 256) {
    throw new Error("maxExclusive must be between 1 and 256");
  }
  const cryptoObj = getCrypto();
  const limit = 256 - (256 % maxExclusive);
  const buf = new Uint8Array(1);

  while (true) {
    cryptoObj.getRandomValues(buf);
    if (buf[0] < limit) {
      return buf[0] % maxExclusive;
    }
  }
}

function getRandomChar(charset: string): string {
  return charset[getSecureRandomInt(charset.length)];
}

export interface PasswordUserContext {
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
}

/**
 * Generate a cryptographically secure random password meeting all Django password validator requirements.
 */
export function generateSecurePassword(context?: PasswordUserContext): string {
  // Substrings of 3+ chars that must not appear in the password to prevent attribute similarity errors
  const disallowed: string[] = [];
  if (context?.firstName && context.firstName.trim().length >= 3) {
    disallowed.push(context.firstName.trim().toLowerCase());
  }
  if (context?.lastName && context.lastName.trim().length >= 3) {
    disallowed.push(context.lastName.trim().toLowerCase());
  }
  if (context?.email) {
    const localPart = context.email.split("@")[0].toLowerCase();
    if (localPart.length >= 3) {
      disallowed.push(localPart);
    }
  }
  if (context?.phone) {
    const digitsOnly = context.phone.replace(/\D/g, "");
    if (digitsOnly.length >= 4) {
      disallowed.push(digitsOnly.slice(-4));
    }
  }

  for (let attempt = 0; attempt < 100; attempt++) {
    // Character distribution:
    // 3 lowercase, 3 uppercase, 3 digits, 2 symbols, 3 from combined = 14 chars
    const chars: string[] = [
      getRandomChar(LOWER),
      getRandomChar(LOWER),
      getRandomChar(LOWER),
      getRandomChar(UPPER),
      getRandomChar(UPPER),
      getRandomChar(UPPER),
      getRandomChar(DIGITS),
      getRandomChar(DIGITS),
      getRandomChar(DIGITS),
      getRandomChar(SYMBOLS),
      getRandomChar(SYMBOLS),
      getRandomChar(ALL_CHARS),
      getRandomChar(ALL_CHARS),
      getRandomChar(ALL_CHARS),
    ];

    // Cryptographic Fisher-Yates shuffle
    for (let i = chars.length - 1; i > 0; i--) {
      const j = getSecureRandomInt(i + 1);
      const temp = chars[i];
      chars[i] = chars[j];
      chars[j] = temp;
    }

    const password = chars.join("");
    const lower = password.toLowerCase();

    // Verify no disallowed attribute substring matches
    const collides = disallowed.some((sub) => lower.includes(sub));
    if (!collides) {
      return password;
    }
  }

  // Fallback in case of collision
  return `${getRandomChar(UPPER)}${getRandomChar(LOWER)}${getRandomChar(DIGITS)}${getRandomChar(SYMBOLS)}${Date.now()}X#`;
}
