import copy
import re
import json
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
from xml.dom import minidom


def _download_json(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


def _upload_json(upload_file_path: str, json_to_upload) -> None:
    with open(upload_file_path, "w", encoding="utf-8") as f:
        json.dump(json_to_upload, f, indent=4)


class DeltaJsonFinder:
    # класс находит delta.json и применяет ее
    def __init__(self, path_to_config_json: str, path_to_patched_config_json: str):
        self.config_json = _download_json(path_to_config_json)
        self.patched_config_json = _download_json(path_to_patched_config_json)
        self.delta = {}

    def find_delta(self):
        self.delta["additions"] = self._find_additions()
        self.delta["deletions"] = self._find_deletions()
        self.delta["updates"] = self._find_updates()
        _upload_json("out/delta.json", self.delta)

    def apply_delta(self):
        res_patched_config_json = copy.deepcopy(self.config_json)

        keys_to_add = self.delta["additions"]
        keys_to_remove = self.delta["deletions"]
        keys_to_update = self.delta["updates"]

        for key in keys_to_remove:
            del res_patched_config_json[key]

        for added_param in keys_to_add:
            res_patched_config_json[added_param["key"]] = added_param["value"]

        for update in keys_to_update:
            key, value = update["key"], update["to"]
            res_patched_config_json[key] = value

        _upload_json("out/res_patched_config.json", res_patched_config_json)

    def _find_additions(self) -> List:
        # поиск добавленных параметров
        additions = []
        added_keys = set(self.patched_config_json.keys()) - set(self.config_json.keys())
        for key in added_keys:
            additions.append({"key": key, "value": self.patched_config_json[key]})
        return additions

    def _find_deletions(self) -> List[str]:
        # поиск удаленных параметров
        deleted_keys = set(self.config_json.keys()) - set(
            self.patched_config_json.keys()
        )
        return list(deleted_keys)

    def _find_updates(self) -> List:
        # поиск изменений в параметрах
        updates = []
        common_key = set(self.config_json.keys()) & set(self.patched_config_json.keys())
        for key in common_key:
            if self.config_json[key] != self.patched_config_json[key]:
                updates.append(
                    {
                        "key": key,
                        "from": self.config_json[key],
                        "to": self.patched_config_json[key],
                    }
                )
        return updates


class InputXmlParser:
    # класс парсит inmpulse_test_input.xml на config.xml и meta json
    def __init__(self, path_to_xml: str):
        tree = ET.parse(path_to_xml)
        self.xml_root: ET.Element = tree.getroot()
        self.new_tree: Optional[ET.ElementTree | None] = None

    def create_meta_json(self) -> None:
        # создание meta.json
        meta: List[Dict[str:Any]] = []
        for elem_class in self.xml_root.findall("Class"):
            elem_info = self._parse_elem_class(elem_class)
            meta.append(elem_info)

        _upload_json("out/meta.json", meta)

    def _parse_elem_class(self, elem_class: ET.Element) -> Dict:
        # поиск всей необходимой информации о elem_class для meta.json
        elem_info: Dict[str:Any] = copy.deepcopy(elem_class.attrib)
        elem_info["isRoot"] = elem_info.get("isRoot").lower() == "true"

        parameters = []
        self._add_source_multiplicity(elem_class, elem_info)

        for attr in elem_class.findall("Attribute"):
            parameters.append({"name": attr.get("name"), "type": attr.get("type")})
        self._add_child_classes(elem_class, parameters)
        elem_info["parameters"] = parameters
        return elem_info

    def _add_source_multiplicity(
        self, elem_class: ET.Element, json_attributes: Dict
    ) -> None:
        # поиск min/max для meta.json
        aggr = self.xml_root.find(f'.//Aggregation[@source="{elem_class.attrib['name']}"]')
        if aggr is None:
            return
        multiplicity: str = aggr.attrib["sourceMultiplicity"]
        min_multiplicity, max_multiplicity = "1", "1"
        if ".." in multiplicity:
            min_multiplicity, max_multiplicity = multiplicity.split("..")
        json_attributes["min"] = min_multiplicity
        json_attributes["max"] = max_multiplicity

    def _add_child_classes(self, elem_class: ET.Element, params: List) -> None:
        # поиск дочерних для elem_class для поля parameters meta.json
        aggregations = self.xml_root.findall(f'.//Aggregation[@target="{elem_class.attrib['name']}"]')
        for agg in aggregations:
            params.append({"name": agg.attrib["source"], "type": "class"})

    def create_config_xml(self) -> None:
        # суффиксы _class_subclass у объекта ET.Element означает принадлежность элемента к вводному xml uml диаграммы
        # а их отсутствие означает принадлежность к новому файлу config.xml

        new_root_class = self.xml_root.find(".//Class[@isRoot='true']")
        if new_root_class is None:
            raise ValueError("Root class not found in XML")

        new_root = ET.Element(new_root_class.attrib["name"])

        for attr in new_root_class.findall("Attribute"):
            ET.SubElement(new_root, attr.get("name")).text = attr.get("type")

        self._add_subclasses(new_root)
        self.new_tree = ET.ElementTree(new_root)
        self._create_output_xml_file()

    def _create_output_xml_file(self) -> None:
        self.new_tree.write("out/config.xml", encoding="utf-8", xml_declaration=True)
        xml_str = minidom.parseString(
            ET.tostring(self.new_tree.getroot(), short_empty_elements=False)
        ).toprettyxml(indent="    ")
        xml_str = self._replace_short_tags(xml_str)
        with open("out/config.xml", "w") as f:
            f.write(xml_str)

    @staticmethod
    def _replace_short_tags(xml_string) -> str:
        # замена тегов на полные, по какой-то причине short_empty_elements=False этого не делает
        return re.sub(
            r"(\s*)(<(\w+)(\s*[^>]*)/>)",
            lambda m: f"{m.group(1)}<{m.group(3)}>{m.group(1)}</{m.group(3)}>",
            xml_string,
        )

    def _add_subclasses(self, parent_elem: ET.Element) -> None:
        # рекурсивный поиск дочерних элементов для parent_elem
        aggregations = self.xml_root.findall(f'.//Aggregation[@target="{parent_elem.tag}"]')
        subclasses_name = [aggr.attrib["source"] for aggr in aggregations]

        for name in subclasses_name:
            elem_subclass = self.xml_root.find(f'.//Class[@name="{name}"]')

            subclass = ET.Element(elem_subclass.attrib["name"])
            subclass.text = ""
            for attr in elem_subclass.findall("Attribute"):
                ET.SubElement(subclass, attr.get("name")).text = attr.get("type")
            parent_elem.append(subclass)
            self._add_subclasses(subclass)


if __name__ == "__main__":
    try:
        input_xml_parser = InputXmlParser("input/impulse_test_input.xml")
        input_xml_parser.create_config_xml()
        input_xml_parser.create_meta_json()

        delta_json_finder = DeltaJsonFinder(
            "input/config.json", "input/patched_config.json"
        )
        delta_json_finder.find_delta()
        delta_json_finder.apply_delta()

        print("Files have generated!")
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        raise
