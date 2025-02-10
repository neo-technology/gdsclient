# reasons for not using nbconvert cli tool:
# * cannot keep output based on a given tag

import argparse
import logging.config
import re
import sys
from pathlib import Path

import nbconvert
from nbconvert.preprocessors import Preprocessor

REPLACE_CELL_OUTPUT_TAG_PATTTERN = r"replace-output-with\:(.*)"
METADATA_TAG_KEY = "tags"

TEMPLATE_DIR = Path("scripts/nb2doc/asciidoc-template")

logging.basicConfig()
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
logger = logging.getLogger()


class OutputReplacerPreprocessor(Preprocessor):
    """
    Replaces the output from tagged code cell in a notebook.
    Expected Tag format `replace-with:images/some.png`
    """

    def __init__(self, replace_base_dir: Path, **kw):
        self._replace_base_dir = replace_base_dir
        super().__init__(**kw)

    def preprocess_cell(self, cell, resources, cell_index):
        """
        Apply a transformation on each cell. See base.py for details.
        """

        if replace_tags := [
            tag for tag in cell["metadata"].get(METADATA_TAG_KEY, []) if re.match(REPLACE_CELL_OUTPUT_TAG_PATTTERN, tag)
        ]:
            if len(replace_tags) > 1:
                raise ValueError(
                    f"Expected one or zero tags matching `{REPLACE_CELL_OUTPUT_TAG_PATTTERN}`. But got `{replace_tags}`"
                )
            new_output_file_name = replace_tags[0].split(":")[1].strip()
            new_ouput_file = self._replace_base_dir.joinpath(new_output_file_name)
            logger.info(f"Replace output with content from: {new_ouput_file}")
            with new_ouput_file.open("r") as new_output:
                # TODO: figure-out schema of cell outputs
                # TODO Implement according to https://nbformat.readthedocs.io/en/latest/format_description.html#display-data
                cell.outputs = [
                    {
                        "output_type": "display_data",
                        "data": {"text/plain": str(new_output)},
                        "metadata": {},
                    }
                ]
                cell.execution_count = None
        return cell, resources


def to_output_file(input_file: Path, output_dir: Path) -> Path:
    return output_dir.joinpath(input_file.name.replace(".ipynb", ".adoc"))


def main(input_path: Path, output_dir: Path) -> None:
    if input_path.is_file():
        notebooks = [input_path]
    else:
        notebooks = [f for f in input_path.iterdir() if f.is_file() and f.suffix == ".ipynb"]

    exporter = nbconvert.ASCIIDocExporter(template_file=str(TEMPLATE_DIR.joinpath("index.adoc.j2")))
    # Skips the "In/Out" lines before each cell
    exporter.exclude_input_prompt = True
    exporter.exclude_output_prompt = True

    metadata_cleaner = nbconvert.preprocessors.ClearMetadataPreprocessor(preserve_cell_metadata_mask=METADATA_TAG_KEY)
    output_replacer = OutputReplacerPreprocessor(replace_base_dir=input_path)

    exporter.register_preprocessor(metadata_cleaner, enabled=True)
    exporter.register_preprocessor(output_replacer, enabled=True)

    logger.info(f"Converting {len(notebooks)} notebooks.")

    for notebook in notebooks:
        output_file = to_output_file(notebook, output_dir)
        logger.info(f"Converting notebook from `{input_path}` to: `{output_file}`")
        output = exporter.from_filename(notebook)

        converted = output[0]

        with output_file.open(mode="w") as out:
            out.write(converted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True, help="directory to write the result to")
    parser.add_argument("-i", "--input", required=True, help="path to the notebook file")

    args = parser.parse_args()

    main(Path(args.input), Path(args.output))
