import { describe, it, expect } from 'vitest';
import { targetTitleFromWikiLink, wikiLinkPattern } from '@/components/MarkdownRenderer';

describe('targetTitleFromWikiLink', () => {
  it('extracts simple title', () => {
    expect(targetTitleFromWikiLink('[[Note Title]]')).toBe('Note Title');
  });

  it('extracts title from pipe syntax', () => {
    expect(targetTitleFromWikiLink('[[Note Title|Display]]')).toBe('Note Title');
  });

  it('trims whitespace', () => {
    expect(targetTitleFromWikiLink('[[  Spaced Title  ]]')).toBe('Spaced Title');
  });

  it('trims whitespace in pipe syntax', () => {
    expect(targetTitleFromWikiLink('[[  A  |  B  ]]')).toBe('A');
  });
});

describe('wikiLinkPattern', () => {
  it('matches simple wikilinks', () => {
    const matches = 'See [[Note A]] and [[Note B]]'.match(wikiLinkPattern);
    expect(matches).toEqual(['[[Note A]]', '[[Note B]]']);
  });

  it('matches pipe wikilinks', () => {
    const matches = 'Link [[Target|display]] here'.match(wikiLinkPattern);
    expect(matches).toEqual(['[[Target|display]]']);
  });

  it('does not match single brackets', () => {
    const matches = 'Not [a link]'.match(wikiLinkPattern);
    expect(matches).toBeNull();
  });

  it('returns null for no wikilinks', () => {
    const matches = 'Plain text without links'.match(wikiLinkPattern);
    expect(matches).toBeNull();
  });
});
