import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const releaseSchema = z.object({
  tag_name: z.string(),
  name: z.string().nullable(),
  published_at: z.string().nullable(),
  created_at: z.string().nullable(),
  prerelease: z.boolean(),
  draft: z.boolean(),
  html_url: z.string()
});

const repositorySchema = z.object({
  slug: z.string(),
  status: z.enum(['ok', 'error']),
  full_name: z.string().optional(),
  description: z.string().nullable().optional(),
  language: z.string().nullable().optional(),
  license: z.string().nullable().optional(),
  topics: z.array(z.string()).optional(),
  stars: z.number().optional(),
  forks: z.number().optional(),
  open_issues: z.number().optional(),
  subscribers: z.number().optional(),
  archived: z.boolean().optional(),
  disabled: z.boolean().optional(),
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  pushed_at: z.string().nullable().optional(),
  releases: z.array(releaseSchema).optional(),
  releases_error: z.string().optional(),
  error: z.string().optional()
});

const snapshots = defineCollection({
  loader: glob({ pattern: '**/*.json', base: '../data' }),
  schema: z.object({
    schema_version: z.number(),
    collector_version: z.string(),
    date: z.string(),
    generated_at: z.string(),
    status: z.enum(['complete', 'partial', 'failed']),
    counts: z.object({
      requested: z.number(),
      ok: z.number(),
      failed: z.number()
    }),
    repositories: z.array(repositorySchema)
  })
});

const reports = defineCollection({
  loader: glob({ pattern: '**/*.md', base: '../reports' })
});

export const collections = { snapshots, reports };
