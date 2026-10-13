"""
This module defines the `SearchFilter` class, responsible for processing raw
search strings and preparing them for use in database queries.

It handles normalization of search terms, identification of quoted phrases
(to be treated as literals), and tokenization of the search string.
The class also determines whether a "fuzzy" or "tokenized" search strategy
should be employed based on factors like database dialect and the nature of
the search query.
"""

import re  # For regular expression operations

from sqlalchemy import Select  # For type hinting SQLAlchemy Select statements
from sqlalchemy.orm import Session  # For type hinting SQLAlchemy Session
from text_unidecode import unidecode  # For removing diacritics from text

# Marvin specific imports
from marvin.db.models import SqlAlchemyBase  # Base SQLAlchemy model
from marvin.schemas._marvin import SearchType, _MarvinModel  # Base Pydantic model and SearchType enum


class SearchFilter:
    """
    Processes a raw search string to prepare it for database querying.

    The process involves:
    0. Determining search type: Fuzzy search (PostgreSQL only, if no quotes in search)
       or tokenized search.
    1. Pre-normalization: Converts punctuation to spaces. Optionally, fully normalizes
       characters (unidecode, lowercase, strip).
    2. Literal extraction: Identifies quoted strings (e.g., "exact phrase") and
       treats them as single search terms, preserving internal spaces.
    3. Tokenization: Splits the remaining (non-quoted) parts of the search string
       into individual tokens based on spaces.
    4. Final list: Combines extracted literals and tokens into a `search_list`.

    The processed `search` string (normalized) and `search_list` (tokens + literals)
    are then used by the `filter_query_by_search` method, which delegates to the
    target schema's `filter_search_query` class method to apply the actual
    SQLAlchemy query conditions.
    """

    # Regex for punctuation characters to be replaced by spaces during normalization.
    # Excludes single and double quotes to preserve them for phrase searching.
    punctuation: str = r"!#$%&()*+,-./:;<=>?@[\\]^_`{|}~"

    # Regex to find quoted substrings (handles both single and double quotes, and escaped quotes within).
    quoted_regex: re.Pattern[str] = re.compile(r"""(["'])(?:(?=(\\?))\2.)*?\1""")

    # Regex to remove the outer quotes from an already extracted quoted string.
    remove_quotes_regex: re.Pattern[str] = re.compile(r"""^['"](.*)['"]$""")  # Added ^ and $ for full match

    @classmethod
    def _normalize_search(cls, search_string: str, normalize_characters: bool) -> str:
        """
        Normalizes a search string.

        Steps:
        1. Replaces punctuation (defined in `cls.punctuation`) with spaces.
        2. If `normalize_characters` is True:
           a. Converts string to ASCII using `unidecode` (removes accents, etc.).
           b. Converts to lowercase.
           c. Strips leading/trailing whitespace.
        3. If `normalize_characters` is False, only strips leading/trailing whitespace.

        Args:
            search_string (str): The raw search string.
            normalize_characters (bool): Whether to perform full character normalization
                                         (unidecode, lowercase).

        Returns:
            str: The normalized search string.
        """
        # Replace specified punctuation characters with spaces
        normalized_s = search_string.translate(str.maketrans(cls.punctuation, " " * len(cls.punctuation)))

        if normalize_characters:
            # Convert to ASCII, lowercase, and strip whitespace
            normalized_s = unidecode(normalized_s).lower().strip()
        else:
            # Only strip whitespace
            normalized_s = normalized_s.strip()

        return normalized_s

    @classmethod
    def _build_search_list(cls, normalized_search_string: str) -> list[str]:
        """
        Builds a list of search terms (tokens and literals) from a normalized search string.

        It first extracts all quoted phrases (literals), removes their outer quotes,
        and stores them. Then, it removes these quoted phrases from the search string,
        replaces punctuation in the remaining parts with spaces, and splits the result
        into individual word tokens. The final list combines the extracted literals
        and word tokens. All terms are stripped of padding whitespace.

        Args:
            normalized_search_string (str): The search string, typically pre-processed by `_normalize_search`.

        Returns:
            list[str]: A list of search terms (quoted literals and individual tokens).
        """
        search_list_final: list[str] = []
        remaining_string_parts = normalized_search_string

        # Extract quoted literals first
        if cls.quoted_regex.search(remaining_string_parts):
            # Find all quoted phrases
            quoted_literals_raw = [match.group(0) for match in cls.quoted_regex.finditer(remaining_string_parts)]

            # Remove outer quotes from these literals and add to final list
            for q_literal_raw in quoted_literals_raw:
                # Use sub() with a lambda to correctly handle stripping one layer of quotes
                # or use remove_quotes_regex.match() and group(1) if it's simpler.
                # The original `cls.remove_quotes_regex.sub("\\1", q_literal_raw)` is fine.
                stripped_literal = cls.remove_quotes_regex.sub(r"\1", q_literal_raw)
                search_list_final.append(stripped_literal.strip())  # Also strip internal padding if any from original quote

            # Remove all quoted phrases from the string to process remaining parts
            remaining_string_parts = cls.quoted_regex.sub("", remaining_string_parts)

        # Process the remaining parts of the string (non-quoted tokens)
        # Replace punctuation with spaces and split into tokens
        if remaining_string_parts.strip():  # Ensure there's something left to process
            token_string = remaining_string_parts.translate(str.maketrans(cls.punctuation, " " * len(cls.punctuation)))
            unquoted_tokens = token_string.split()  # Split by spaces
            search_list_final.extend(unquoted_tokens)

        # Final strip for all collected terms (though individual parts should be stripped already)
        return [term.strip() for term in search_list_final if term.strip()]  # Ensure no empty strings

    def __init__(self, session: Session, search_query: str, normalize_characters: bool = False) -> None:
        """
        Initializes the SearchFilter.

        Determines the `search_type` (fuzzy or tokenized) based on the database dialect
        (PostgreSQL supports fuzzy) and whether the search query contains quoted phrases
        (quoted phrases force tokenized search).
        Normalizes the search query and builds a list of search terms.

        Args:
            session (Session): The SQLAlchemy session, used to determine DB dialect.
            search_query (str): The raw search string from the user.
            normalize_characters (bool, optional): If True, performs aggressive character
                                                   normalization (unidecode, lowercase).
                                                   Defaults to False.
        """
        self.session: Session = session

        # Determine search type:
        # Fuzzy search is preferred for PostgreSQL if the query is simple (no quoted literals).
        # Quoted literals imply the user wants exact phrase matching within those quotes,
        # which is better handled by tokenized search logic (e.g., using LIKE for literals).
        is_postgresql = session.get_bind().name == "postgresql"
        contains_quoted_literals = self.quoted_regex.search(search_query.strip()) is not None

        self.search_type: SearchType
        if is_postgresql and not contains_quoted_literals:
            self.search_type = SearchType.fuzzy
        else:
            self.search_type = SearchType.tokenized

        # Normalize the raw search query.
        self.search: str = self._normalize_search(search_query, normalize_characters)
        # Build the list of search terms (tokens and literals).
        self.search_list: list[str] = self._build_search_list(self.search)

    def filter_query_by_search(self, query: Select, schema_class: type[_MarvinModel], db_model_class: type[SqlAlchemyBase]) -> Select:
        """
        Applies the processed search terms to a SQLAlchemy query.

        This method delegates the actual query modification to the
        `filter_search_query` class method of the provided `schema_class`.
        The schema class is expected to know which of its fields are searchable
        and how to apply the `search_type`, normalized `search` string, and
        `search_list` to the query for the given `db_model_class`.

        Args:
            query (Select): The SQLAlchemy Select query to be filtered.
            schema_class (type[_MarvinModel]): The Pydantic schema corresponding to the `db_model_class`.
                                            It should have a `filter_search_query` method.
            db_model_class (type[SqlAlchemyBase]): The SQLAlchemy model class to be queried.

        Returns:
            Select: The modified SQLAlchemy Select query with search filters applied.
        """
        # Delegate to the schema's static/class method for applying the search.
        # This allows search logic to be customized per schema/model.
        return schema_class.filter_search_query(
            db_model=db_model_class,
            query=query,
            session=self.session,  # Pass session for dialect-specific features like pg_trgm settings
            search_type=self.search_type,
            search=self.search,  # Full normalized search string
            search_list=self.search_list,  # List of tokens and literals
        )
