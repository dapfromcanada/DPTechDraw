# Copyright 2006 The QElectroTech Team
# This file is part of QElectroTech.
#
# QElectroTech is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# QElectroTech is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with QElectroTech. If not, see <http://www.gnu.org/licenses/>.

message(" - fetch_pugixml")

Include(FetchContent)

option(BUILD_PUGIXML "Build pugixml library, use system one otherwise" YES)

if(BUILD_PUGIXML)
  # This version keeps its own copy of pugixml (1.15) in the source tree.
  # Nothing is downloaded, and headers and library come from the same copy.
  if(NOT EXISTS "${CMAKE_SOURCE_DIR}/pugixml/CMakeLists.txt")
    message(FATAL_ERROR "pugixml/ is missing from the source tree")
  endif()
  add_subdirectory("${CMAKE_SOURCE_DIR}/pugixml"
                   "${CMAKE_BINARY_DIR}/local_pugixml")
else()
  find_package(pugixml REQUIRED)
endif()
