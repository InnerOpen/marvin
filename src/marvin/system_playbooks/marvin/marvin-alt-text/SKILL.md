---
name: marvin-alt-text
description: Use when writing or checking alt text for an image, or when you add an image to an entry, a social post or the asset library and it has none. Decides whether the image needs a description at all, then how to write one that works for someone who can't see it.
disable-model-invocation: false
---

# Alt text for an image

Alt text stands in for an image for people who can't see it: screen reader users, anyone on a slow connection, search
engines. Write the one or two sentences a person would say if they were reading the page aloud to a friend.

If this workspace has a voice or style Playbook in your list, load it and let it decide how the sentence sounds. This one
covers what the text has to do. For how the asset library works (assets, versions, where an image is used), call
`read_doc` with `path` `whats-new/index.md` and `section` `assets-library`.

## 1. Look at the image

`view_image` shows you the picture itself. Don't write alt text from a file name, a title or the entry around it: describe
what is actually in the image. If the image is already an asset, `get_asset` shows the alt text it has now.

## 2. Does it need a description?

- **Informative** (a photo, diagram, screenshot, chart that adds something): describe it, below.
- **Decorative** (a divider, a background texture, an icon next to a label that says the same thing): it needs no
  description. Leave the alt text empty on purpose rather than filling it with filler, so a screen reader skips it. Say
  in your reply that you treated it as decorative.
- **It repeats the text beside it** (a photo whose caption already says everything): keep the alt text short, and don't
  say again what the caption says.

When you can't tell which it is, ask what the image is doing on the page.

## 3. Write it

1. Say what matters about the image **in the context where it appears**. The same photo of a seam needs different words in a
   how-to than in a product listing.
2. Be concrete and short. Aim for **125 characters or fewer**; go over only when the image carries real information (a
   chart, a diagram) and then say it in the fewest words that work.
3. Start with the subject. Leave out "image of", "photo of" and "picture of": the screen reader already says it is an image.
4. **Text in the image:** transcribe it, word for word, when it matters.
5. **A chart or diagram:** give the point it makes ("Sales doubled between March and June"), not a list of every bar. Put
   the full data in the page text if it matters.
6. **People:** say what they are doing. Name a person only when the page names them too.
7. Don't guess what you can't see. If the image is unclear, describe what is clear and say so in your reply.

`references/examples.md` has before and after examples.

## 4. Put it where it belongs

- **An image in markdown:** `![alt text](url)`, the text between the brackets.
- **An image field or attached image on an entry:** save the text in the asset's alt text, not only in the entry, so every
  page that uses the image gets it.
- **A social post:** networks take a description per picture, separate from the post text. Write one for each image.
- **A new asset:** pass `alt_text` to `import_asset` when you import it.
- **An asset that already exists:** there is no tool that changes an existing asset's alt text. Give the text in your reply,
  or in the draft for the entry, and say that someone has to paste it into the asset's page.

## 5. Check before you finish

- Would it make sense read aloud, with the image gone?
- Is it under about 125 characters, or does it earn the extra length?
- Does it start with the subject, with no "image of"?
- Did you say which images you left empty as decorative, and why?
