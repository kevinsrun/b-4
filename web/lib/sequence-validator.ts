/**
 * Scientific sequence validation and FASTA parsing.
 *
 * Implements strict canonical amino acid verification matching the backend's
 * `SequenceInput` schema in `bacteriocin_lab/amp/schemas.py`.
 */

import type { SequenceInput } from "./amp-types";

export const CANONICAL_AMINO_ACIDS = new Set("ACDEFGHIKLMNPQRSTVWY".split(""));

export interface ValidationIssue {
  field: "sequence_id" | "sequence" | "batch";
  index?: number;
  sequence_id?: string;
  message: string;
  severity: "error" | "warning";
}

export interface ValidatedSequence {
  sequence_id: string;
  sequence: string;
  length: number;
  checksum: string;
  isValid: boolean;
  issues: ValidationIssue[];
  modelEligibility: Record<string, { eligible: boolean; reason?: string }>;
}

export interface BatchValidationResult {
  isValid: boolean;
  sequences: ValidatedSequence[];
  totalResidues: number;
  duplicateIds: string[];
  duplicateChecksums: string[];
  issues: ValidationIssue[];
}

/**
 * Synchronous client-side SHA-256 implementation using SHA-256 algorithm
 * for instant hashing without async browser crypto overhead or SSR issues.
 */
export function sha256Sync(ascii: string): string {
  function rightRotate(value: number, amount: number) {
    return (value >>> amount) | (value << (32 - amount));
  }

  const mathPow = Math.pow;
  const maxWord = mathPow(2, 32);
  const lengthProperty = "length";
  let i = 0, j = 0;
  let result = "";

  const words: number[] = [];
  const asciiBitLength = ascii[lengthProperty] * 8;

  let hash = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];

  const k = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];

  let currentBlockIndex = 0;
  for (i = 0; i < ascii[lengthProperty]; i++) {
    const code = ascii.charCodeAt(i);
    currentBlockIndex = i >> 2;
    words[currentBlockIndex] |= code << (24 - (i % 4) * 8);
  }

  currentBlockIndex = i >> 2;
  words[currentBlockIndex] |= 0x80 << (24 - (i % 4) * 8);
  words[(((asciiBitLength + 64) >> 9) << 4) + 15] = asciiBitLength;

  const w = new Array(64);
  for (let blockStart = 0; blockStart < words.length; blockStart += 16) {
    const subHash = hash.slice(0);

    for (i = 0; i < 64; i++) {
      if (i < 16) {
        w[i] = words[blockStart + i] | 0;
      } else {
        const gamma0 = rightRotate(w[i - 15], 7) ^ rightRotate(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const gamma1 = rightRotate(w[i - 2], 17) ^ rightRotate(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + gamma0 + w[i - 7] + gamma1) | 0;
      }

      const s1 = rightRotate(subHash[4], 6) ^ rightRotate(subHash[4], 11) ^ rightRotate(subHash[4], 25);
      const ch = (subHash[4] & subHash[5]) ^ (~subHash[4] & subHash[6]);
      const temp1 = (subHash[7] + s1 + ch + k[i] + w[i]) | 0;
      const s0 = rightRotate(subHash[0], 2) ^ rightRotate(subHash[0], 13) ^ rightRotate(subHash[0], 22);
      const maj = (subHash[0] & subHash[1]) ^ (subHash[0] & subHash[2]) ^ (subHash[1] & subHash[2]);
      const temp2 = (s0 + maj) | 0;

      subHash[7] = subHash[6];
      subHash[6] = subHash[5];
      subHash[5] = subHash[4];
      subHash[4] = (subHash[3] + temp1) | 0;
      subHash[3] = subHash[2];
      subHash[2] = subHash[1];
      subHash[1] = subHash[0];
      subHash[0] = (temp1 + temp2) | 0;
    }

    for (j = 0; j < 8; j++) {
      hash[j] = (hash[j] + subHash[j]) | 0;
    }
  }

  for (i = 0; i < 8; i++) {
    for (j = 3; j >= 0; j--) {
      const b = (hash[i] >> (j * 8)) & 255;
      result += (b < 16 ? "0" : "") + b.toString(16);
    }
  }

  return result;
}

/** Check eligibility of a sequence against known model requirements. */
export function checkModelEligibility(
  length: number,
  modelId: string,
): { eligible: boolean; reason?: string } {
  switch (modelId) {
    case "ampir":
      if (length < 10) {
        return { eligible: false, reason: "ampir requires at least 10 residues" };
      }
      return { eligible: true };
    case "ampeppy":
      if (length < 1) {
        return { eligible: false, reason: "amPEPpy requires at least 1 residue" };
      }
      return { eligible: true };
    case "amplify":
      if (length < 2 || length > 200) {
        return { eligible: false, reason: "AMPlify domain is 2–200 residues (model is BLOCKED)" };
      }
      return { eligible: false, reason: "Model is unavailable (BLOCKED)" };
    case "ampscanner_v2":
      if (length < 10 || length > 200) {
        return { eligible: false, reason: "AMPScanner domain is 10–200 residues (model is BLOCKED)" };
      }
      return { eligible: false, reason: "Model is unavailable (BLOCKED)" };
    case "ai4amp":
      return { eligible: false, reason: "Model is unavailable (BLOCKED)" };
    case "apin":
      return { eligible: false, reason: "Model is unavailable (BLOCKED)" };
    default:
      return { eligible: true };
  }
}

/** Validate an individual sequence according to backend contracts. */
export function validateSequence(
  sequence_id: string,
  rawSequence: string,
  index = 0,
): ValidatedSequence {
  const issues: ValidationIssue[] = [];
  const cleanId = sequence_id.trim();
  const cleanSeq = rawSequence.replace(/\s+/g, "");

  // Validate ID
  if (!cleanId) {
    issues.push({
      field: "sequence_id",
      index,
      message: "Sequence identifier cannot be empty.",
      severity: "error",
    });
  } else {
    if (cleanId.length > 100) {
      issues.push({
        field: "sequence_id",
        index,
        sequence_id: cleanId,
        message: "Sequence identifier cannot exceed 100 characters.",
        severity: "error",
      });
    }
    const idPattern = /^[A-Za-z0-9_.:-]+$/;
    if (!idPattern.test(cleanId)) {
      issues.push({
        field: "sequence_id",
        index,
        sequence_id: cleanId,
        message: "Identifier may only contain letters, numbers, underscores, dots, colons, and hyphens.",
        severity: "error",
      });
    }
  }

  // Validate Sequence
  if (!cleanSeq) {
    issues.push({
      field: "sequence",
      index,
      sequence_id: cleanId,
      message: "Sequence is empty.",
      severity: "error",
    });
  } else {
    if (cleanSeq.length > 10000) {
      issues.push({
        field: "sequence",
        index,
        sequence_id: cleanId,
        message: `Sequence length (${cleanSeq.length}) exceeds 10,000 residue limit.`,
        severity: "error",
      });
    }

    const invalidChars: string[] = [];
    for (let i = 0; i < cleanSeq.length; i++) {
      const char = cleanSeq[i];
      if (!CANONICAL_AMINO_ACIDS.has(char)) {
        if (!invalidChars.includes(char)) {
          invalidChars.push(char);
        }
      }
    }

    if (invalidChars.length > 0) {
      issues.push({
        field: "sequence",
        index,
        sequence_id: cleanId,
        message: `Contains non-canonical or ambiguous residues: '${invalidChars.join("', '")}'. Only canonical uppercase amino acids (ACDEFGHIKLMNPQRSTVWY) without gaps or stop codons are permitted.`,
        severity: "error",
      });
    }
  }

  const checksum = cleanSeq ? sha256Sync(cleanSeq) : "";
  const length = cleanSeq.length;

  const modelEligibility: Record<string, { eligible: boolean; reason?: string }> = {
    ampir: checkModelEligibility(length, "ampir"),
    ampeppy: checkModelEligibility(length, "ampeppy"),
    amplify: checkModelEligibility(length, "amplify"),
    ampscanner_v2: checkModelEligibility(length, "ampscanner_v2"),
    ai4amp: checkModelEligibility(length, "ai4amp"),
    apin: checkModelEligibility(length, "apin"),
  };

  const hasErrors = issues.some((issue) => issue.severity === "error");

  return {
    sequence_id: cleanId,
    sequence: cleanSeq,
    length,
    checksum,
    isValid: !hasErrors,
    issues,
    modelEligibility,
  };
}

/** Validate a batch of sequences against global and local constraints. */
export function validateBatch(inputs: { sequence_id: string; sequence: string }[]): BatchValidationResult {
  const issues: ValidationIssue[] = [];
  const validatedSequences: ValidatedSequence[] = [];
  let totalResidues = 0;

  if (inputs.length === 0) {
    issues.push({
      field: "batch",
      message: "At least one sequence must be provided.",
      severity: "error",
    });
  }

  if (inputs.length > 128) {
    issues.push({
      field: "batch",
      message: `Batch size (${inputs.length}) exceeds maximum limit of 128 sequences.`,
      severity: "error",
    });
  }

  const seenIds = new Map<string, number>();
  const duplicateIds: string[] = [];
  const seenChecksums = new Map<string, number>();
  const duplicateChecksums: string[] = [];

  inputs.forEach((input, index) => {
    const validated = validateSequence(input.sequence_id, input.sequence, index);
    validatedSequences.push(validated);
    totalResidues += validated.length;

    // Check duplicate ID
    if (validated.sequence_id) {
      if (seenIds.has(validated.sequence_id)) {
        if (!duplicateIds.includes(validated.sequence_id)) {
          duplicateIds.push(validated.sequence_id);
        }
        validated.issues.push({
          field: "sequence_id",
          index,
          sequence_id: validated.sequence_id,
          message: `Duplicate sequence identifier '${validated.sequence_id}'.`,
          severity: "error",
        });
        validated.isValid = false;
      } else {
        seenIds.set(validated.sequence_id, index);
      }
    }

    // Check duplicate sequence checksum
    if (validated.checksum) {
      if (seenChecksums.has(validated.checksum)) {
        if (!duplicateChecksums.includes(validated.checksum)) {
          duplicateChecksums.push(validated.checksum);
        }
        validated.issues.push({
          field: "sequence",
          index,
          sequence_id: validated.sequence_id,
          message: `Identical sequence content detected in batch (SHA-256: ${validated.checksum.slice(0, 10)}...).`,
          severity: "warning",
        });
      } else {
        seenChecksums.set(validated.checksum, index);
      }
    }
  });

  if (duplicateIds.length > 0) {
    issues.push({
      field: "batch",
      message: `Batch contains ${duplicateIds.length} duplicate sequence identifier(s): ${duplicateIds.join(", ")}. Identifiers must be strictly unique.`,
      severity: "error",
    });
  }

  if (totalResidues > 128000) {
    issues.push({
      field: "batch",
      message: `Batch total residues (${totalResidues.toLocaleString()}) exceeds limit of 128,000 residues.`,
      severity: "error",
    });
  }

  const allValid =
    issues.every((i) => i.severity !== "error") &&
    validatedSequences.every((s) => s.isValid);

  return {
    isValid: allValid,
    sequences: validatedSequences,
    totalResidues,
    duplicateIds,
    duplicateChecksums,
    issues,
  };
}

/** Parse Multi-FASTA string into SequenceInput items. */
export function parseFasta(text: string): SequenceInput[] {
  const lines = text.split(/\r?\n/);
  const items: SequenceInput[] = [];
  let currentId = "";
  let currentSeqParts: string[] = [];
  let unnamedCount = 1;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith(";")) {
      continue;
    }
    if (trimmed.startsWith(">")) {
      if (currentId || currentSeqParts.length > 0) {
        items.push({
          sequence_id: currentId || `seq_${unnamedCount++}`,
          sequence: currentSeqParts.join(""),
        });
        currentSeqParts = [];
      }
      // Extract identifier before first whitespace or bar if suitable
      const header = trimmed.slice(1).trim();
      const firstToken = header.split(/\s+/)[0] || `seq_${unnamedCount++}`;
      // Sanitize token for standard identifier pattern
      currentId = firstToken.replace(/[^A-Za-z0-9_.:-]/g, "_");
    } else {
      currentSeqParts.push(trimmed);
    }
  }

  if (currentId || currentSeqParts.length > 0) {
    items.push({
      sequence_id: currentId || `seq_${unnamedCount++}`,
      sequence: currentSeqParts.join(""),
    });
  }

  return items;
}

/** Convert sequence inputs back into Multi-FASTA format. */
export function toFasta(sequences: SequenceInput[]): string {
  return sequences
    .map((s) => {
      // Wrap sequence lines at 60 or 70 chars for canonical FASTA
      const chunked = s.sequence.match(/.{1,70}/g)?.join("\n") ?? s.sequence;
      return `>${s.sequence_id}\n${chunked}`;
    })
    .join("\n\n");
}
