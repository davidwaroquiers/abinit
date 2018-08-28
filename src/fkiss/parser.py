"""
"""
from __future__ import print_function, division, unicode_literals, absolute_import

import os
import re

from textwrap import TextWrapper
from pprint import pformat
from collections import OrderedDict, defaultdict, deque
from .termcolor import cprint
from .tools import lazy_property
from .regex import HasRegex


class Node(object):

    def __repr__(self):
        if self.ancestor is not None:
            return "<%s: %s.%s>" % (self.__class__.__name__, self.ancestor.name, self.name)
        else:
            return "<%s: %s>" % (self.__class__.__name__, self.name)

    def __str__(self):
        # FIXME: This is ABC
        return self.to_string()

    @staticmethod
    def terminal_highlight(s, bg="dark"):
        try:
            from pygments import highlight
        except ImportError:
            return s

        from pygments.lexers import FortranLexer
        from pygments.formatters import TerminalFormatter
        return highlight(s, FortranLexer(), TerminalFormatter(bg=bg))


class FortranVariable(Node):
    """
    Fortran Variable.
    type-spec[ [, att] ... :: ] v[/c-list/][, v[/c-list/]] ...
    """

    #def __init__(self,name,vartype,parent,attribs=[],intent="",
    #             optional=False,permission="public",kind=None,
    #             strlen=None,proto=None,doc=[],points=False,initial_value=None):

    def __init__(self, name, ancestor, ftype, shape, kind=None, strlen=None,
                 attribs=None, initial_value=None, doc=None):

        self.name, self.ancestor = name, ancestor
        self.attribs = () if attribs is None else tuple(sorted(attribs))
        self.ftype, self.shape = ftype, shape
        # TODO: dimension
        #print(self.attribs)
        #if "dimension" in attribs:
        #    self.shape = attribs["dimension"].replace(" ", "").replace("dimension", "")
        #    print("shape", self.shape)

        self.initial_value = initial_value
        self.doc = "" if doc is None else doc

        if ftype == "character":
            if kind is not None:
                raise ValueError("ftype: %s, kind: %s, strlen: %s" % (ftype, kind, strlen))
            self.strlen = strlen
        else:
            if strlen is not None:
                raise ValueError("ftype: %s, kind: %s, strlen: %s" % (ftype, kind, strlen))
            self.kind = kind

    def to_string(self, verbose=0):
        return "foo"

    @lazy_property
    def is_scalar(self):
        return not bool(self.shape)

    @lazy_property
    def is_array(self):
        return bool(self.shape)

    @lazy_property
    def is_allocatable(self):
        return "allocatable" in self.attribs

    @lazy_property
    def is_pointer(self):
        return "pointer" in self.attribs

    #@lazy_property
    #def is_pointer_set_to_null(self):
    #    if not self.is_pointer: return False
    #    return self.initial_value == "null()"


class Datatype(Node, HasRegex):

    def __init__(self, name, ancestor, lines):
        self.name, self.ancestor = name, ancestor
        self.lines = lines
        self._analyzed = False

    def to_string(self, verbose=0):
        s = "\n".join(self.lines)
        return s

    #def __getattr__(self, name):
    #    """Called when an attribute lookup has not found the attribute in the usual places"""
    #    if not self._analyzed:
    #        self.analyze()
    #        return super(Datatype, self).__getattr__(name)
    #    else:
    #        raise AttributeError("Cannot find attributed `%s`" % str(name))

    def analyze(self, verbose=0):
        if self._analyzed: return
        self._analyzed = True
        if verbose: print(self.terminal_highlight("\n".join(self.lines)))
        self.variables = OrderedDict()
        doc = []
        names = None
        visibility = "public"

        for i, line in enumerate(self.lines):
            line = line.strip()
            if i == 0 and not line.startswith("type"): raise ValueError(line)
            if i == len(self.lines) - 1 and not line.startswith("end"): raise ValueError(line)
            if i in (0, len(self.lines) -1): continue
            if not line or line.startswith("#"): continue

            if line in ("private", "public"):
                visibility = line
                continue

            if line.startswith("!"):
                doc.append(line)
            else:
                # New variable found.
                if names is not None:
                    for i, name in enumerate(names):
                        print("Creating var:", name)
                        var = FortranVariable(name, self, ftype, shapes[i], kind=kind, strlen=None,
                                              attribs=attribs, initial_value=initial_values[i], doc="n".join(doc))
                        self.variables[name] = var
                        doc = []

                # Assume: integer, attr1, attr2 :: varname(...)
                line = line.replace(" ", "")
                if verbose: print(line)
                #print(line)
                # Handle inlined comment.
                i = line.find("!")
                if i != -1:
                    doc.append(line[i:])
                    line = line[:i]

                if "::" not in line: raise ValueError(line)
                pre, post = line.split("::")
                toks = pre.split(",")
                ftype = toks[0]
                attribs = [] if len(toks) == 1 else toks[1:]

                # Extract ftype and kind
                # TODO
                kind, strlen = None, None
                m = self.RE_CHARACTER_DEC.match(ftype)
                if m:
                    ftype = "character"
                    strlen, kind = m.group("len"), None

                m = self.RE_TYPECLASS_DEC.match(ftype)
                if m:
                    ftype, kind, strlen = m.group("ftype"), m.group("name"), None

                m = self.RE_NUMBOOL_DEC.match(ftype)
                if m:
                    ftype, kind, strlen = m.group("ftype"), m.group("kind"), None

                # TODO: a(1,2), b, c(3, 4)
                if ")" in post:
                    vlist = post.split("),")
                    for i, v in enumerate(vlist):
                        if "(" in v and not v.endswith(")"):
                            vlist[i] = v + ")"
                else:
                    vlist = post.split(",")

                # Extract default values from vlist (e.g. `a = zero`)
                initial_values = [None] * len(vlist)
                for i, v in enumerate(vlist):
                    if "=" in v:
                        print(v)
                        v, default = v.split("=", 1)
                        vlist[i] = v
                        initial_values[i] = default

                # Extract shapes from vlist (None if scalar)
                names = [None] * len(vlist)
                shapes = [None] * len(vlist)
                for iv, v in enumerate(vlist):
                    names[iv] = v
                    j = v.find("(")
                    if j != -1:
                        if v[-1] != ")": raise ValueError(v)
                        names[iv] = v[:j]
                        shapes[iv] = v[j:]

                #if verbose:
                #    print(f"ftype={ftype}, attribs={attribs}, vlist={vlist}, names={names}, shapes={shapes}, initial_values={initial_values}\n".format(locals()))

        for i, name in enumerate(names):
            var = FortranVariable(name, self, ftype, shapes[i], kind=kind, strlen=strlen,
                                  attribs=attribs, initial_value=initial_values[i], doc="\n".join(doc))
            self.variables[name] = var


class Interface(Node):

    def __init__(self, name, ancestor, lines):
        self.name, self.ancestor = name, ancestor
        self.lines = lines
        self._analyzed = False

    def to_string(self, verbose=0):
        s = "\n".join(self.lines)
        return s

    def analyze(self, verbose=0):
        if self._analyzed: return
        self._analyzed = True


class Procedure(Node):
    """
    Base class for programs/routines/functions/modules.

    contains: List of contained `Procedure`
    local_uses: List of strings with the name of the modules used (explicit) by this procedure
    includes: List of strings with the name of the included file.
    parents: List of `Procedure` calling this one
    children: List of string with the name of the subroutines called by this procedure.
    """

    def __init__(self, name, ancestor, preamble, path="<UnknownFile>"):
        self.name = name.strip()
        self.ancestor = ancestor
        self.preamble = "\n".join(preamble)
        self.path = path
        self.basename = os.path.basename(self.path)

        self.num_f90lines, self.num_doclines, self.num_omp_statements = 0, 0, 0
        self.contains, self.local_uses, self.includes = [], [], []
        self.parents, self.children = [], []
        self.types = []
        self.interfaces = []

        # TODO
        # Initialize visibility.
        # The real value will be set by analyzing the module.
        self.visibility = "public"
        #self.has_implicit_none = False

    @lazy_property
    def is_program(self):
        return isinstance(self, Program)

    @lazy_property
    def is_module(self):
        return isinstance(self, Module)

    @lazy_property
    def is_subroutine(self):
        return isinstance(self, Subroutine)

    @lazy_property
    def is_function(self):
        return isinstance(self, Function)

    #@lazy_property
    #def visibility(self):
    #    # visibility of modules is assumed to be initialized.
    #    return self._visibility
    #    if self._visibility is not None: return self._visibility
    #    if self.is_program: return True

    #    if self.ancestor is not None:
    #        if self.ancestor.is_subroutine or self.ancestor.is_function or self.ancestor.is_program:
    #            self._visibility = False
    #            return self._visibility

    #    ancestor = self.ancestor
    #    while ancestor is not None:
    #        if ancestor.is_module:
    #            self._visibility = ancestor.visibility
    #            return self._visibility
    #        ancestor = self.ancestor

    #    # Procedure outside module
    #    #print(repr(self))
    #    #raise RuntimeError("you should not be here!")
    #    self._visibility = True
    #    return self._visibility

    @lazy_property
    def dirpath(self):
        """Absolute path of the directory in which the procedure is located."""
        return None if self.path is None else os.path.dirname(self.path)

    @lazy_property
    def dirname(self):
        """name of the directory in which the procedure is located."""
        return None if self.path is None else os.path.basename(os.path.dirname(self.path))

    @lazy_property
    def dirlevel(self):
        if self.dirname is None:
            return -1
        else:
            # 72_response --> 72
            return int(self.dirname.split("_")[0])

    @property
    def is_public(self):
        return self.visibility == "public"

    @property
    def is_private(self):
        return self.visibility == "private"

    #@lazy_property
    #def global_uses(self)
    #    """String with all the modules used by this procedure (locals + globals)"""

    @lazy_property
    def public_procedures(self):
        """List of public procedures."""
        if self.is_program:
            return [self]
        elif self.is_module:
            return [self] + [p for p in self.contains if p.is_public]
        elif self.is_subroutine or self.is_function:
            return [self]  if self.is_public else []
        raise TypeError("Don't know how to find public entities of type: %s" % type(self))

    def stree(self, level=0):
        lines = [level * "\t" + repr(self)]; app = lines.append
        level += 1
        for p in self.contains:
            app(p.stree(level=level))

        return "\n".join(lines)

    def to_string(self, verbose=0, width=90):
        """
        String representation with verbosity level `verbose`.
        Text is wrapped at `width` columns.
        """
        w = TextWrapper(initial_indent="\t", subsequent_indent="\t", width=width)
        lines = []; app = lines.append

        app("%s: %s\n" % (self.__class__.__name__.upper(), self.name))
        app("Directory: %s" % os.path.basename(self.dirname))

        if self.ancestor is not None:
            app("ANCESTOR:\n\t%s (%s)" % (self.ancestor.name, self.ancestor.__class__.__name__))
        if self.uses:
            app("USES:\n%s\n" % w.fill(", ".join(self.uses)))
            diff = sorted(set(self.local_uses) - set(self.uses))
            if diff:
                app("LOCAL USES:\n%s\n" % w.fill(", ".join(diff)))
        if self.includes:
            app("INCLUDES:\n%s\n" % w.fill(", ".join(self.includes)))
        if self.contains:
            app("CONTAINS:\n%s\n" % w.fill(", ".join(c.name for c in self.contains)))

        if self.types:
            app("DATATYPES:\n%s\n" % w.fill(", ".join(d.name for d in self.types)))
        if self.interfaces:
            app("INTERFACES:\n%s\n" % w.fill(", ".join(i.name for i in self.interfaces)))

        app("PARENTS:\n%s\n" % w.fill(", ".join(sorted(p.name for p in self.parents))))
        #if verbose:
        # Add directory of parents
        dirnames = sorted(set(os.path.basename(p.dirname) for p in self.parents))
        app("PARENT_DIRS:\n%s\n" % w.fill(", ".join(dirnames)))

        app("CHILDREN:\n%s\n" % w.fill(", ".join(sorted(c for c in self.children))))

        if verbose > 1:
            app("")
            app("number of Fortran lines:%s" % self.num_f90lines)
            app("number of doc lines: %s" % self.num_doclines)
            app("number of OpenMP statements: %s" % self.num_omp_statements)
            # Add directory of children
            #dirnames = sorted(set(os.path.basename(p.dirname) for p in self.children))
            #app("CHILDREN_DIRS:\n%s\n" % w.fill(", ".join(dirnames)))
            app("PREAMBLE:\n%s" % self.preamble)

        return "\n".join(lines)

    @lazy_property
    def uses(self):
        """
        List of strings with the modules used by this procedure.
        The list includes the modules used explicitly inside the procedure as well as
        the modules imported at the module level.
        """
        uses = self.local_uses[:]
        if self.is_module or self.is_program:
            for p in self.contains:
                uses.extend(p.local_uses)
                # TODO: should be recursive
                for c in p.contains:
                    uses.extend(c.local_uses)

        elif self.is_subroutine or self.is_function:
            ancestor = self.ancestor
            while ancestor is not None:
                uses.extend(ancestor.local_uses)
                ancestor = ancestor.ancestor

        else:
            raise TypeError("Don't know how to handle %s" % type(self))

        return sorted(set(uses))


class Program(Procedure):
    """Fortran program."""
    proc_type = "program"


class Function(Procedure):
    """Fortran function."""
    proc_type = "function"


class Subroutine(Procedure):
    """Fortran subroutine."""
    proc_type = "subroutine"


class Module(Procedure):
    """Fortran module."""
    proc_type = "module"

    def __init__(self, name, ancestor, preamble, path=None):
        super(Module, self).__init__(name, ancestor, preamble, path=path)
        self.default_visibility = True
        #self.variables = OrderedDict()
        #self.public_procedure_names = []
        #self.private_procedure_names = []

    def to_string(self, verbose=0, width=90):
        lines = []; app = lines.append
        app(super(Module, self).to_string(verbose=verbose, width=width))
        #w = TextWrapper(initial_indent="\t", subsequent_indent="\t", width=width)
        return "\n".join(lines)


class FortranKissParser(HasRegex):
    """
    Parse fortran code.
    """

    def __init__(self, macros=None, verbose=0):
        self.verbose = verbose
        self.macros = {} if macros is None else macros

    def parse_file(self, path):
        with open(path, "rt") as fh:
            string = fh.read()

            # TODO: Include Fortran files?
            #lines = []
            #for line in string.splitlines():
            #    l =  line.strip().replace("'", "").replace('"', "")
            #    if l.startswith("#include") and (l.endswith(".finc") or l.endswith(".F90")):
            #        basename = l.split()[-1]
            #        with open(os.path.join(os.path.dirname(path), basename), "rt") as incfh:
            #            lines.extend(incfh.readlines())
            #    else:
            #        lines.append(line)
            #string = "\n".join(lines)

            return self.parse_string(string, path=path)

    def parse_string(self, string, path=None):
        if path is None: path = "<UnknownPath>"
        self.path = path

        # Replace macros. Needed e.g. to treat USE_DEFS macros in libpaw and tetralib.
        for macro, value in self.macros.items():
            string = re.sub(macro, value, string)

        # Perhaps here one should join multiple lines ending with &
        # Get list of lower-case string.
        #self.lines = deque(l.strip().lower() for l in string.splitlines())
        self.lines = deque(l.strip() for l in string.splitlines())
        #self.lines = deque(l for l in string.splitlines())
        self.warnings = []

        self.num_doclines, self.num_f90lines, self.num_omp_statements = 0, 0, 0
        self.preamble, self.stack = [], []
        self.all_includes, self.all_uses  = [], []
        self.ancestor = None

        # Invokations of Fortran functions are difficult to handle
        # without inspecting locals so we only handle explicit calls to routines.
        # in principle I may re-read the source and use regex for val = foo() where foo in one of the routines
        # but it's gonna be costly.

        while self.lines:
            line = self.lines.popleft()
            if not line: continue
            if self.handle_comment(line): continue
            line = line.lower()
            if self.handle_use_statement(line): continue
            if self.handle_cpp_line(line): continue
            if self.handle_contains(line): continue
            if self.handle_call(line): continue

            # Subroutine|Function declaration.
            if self.handle_procedure(line): continue
            if self.consume_module_header(line): continue

            #m = self.RE_PROC_END.match(line)
            m = self.RE_MOD_END.match(line)
            if m:
                #print(line)
                #end_proc_type = m.group("proc_type")
                end_proc_type = "module"
                end_name = m.group("name")
                self.close_stack_entry(end_name, end_proc_type)
                continue

        self.all_includes = sorted(set(self.all_includes))
        self.all_uses = sorted(set(self.all_uses))

        # Extract data from stack.
        # TODO: Support visibility But I need to parse the first portion of the header.
        # to handle e.g. public :: foo
        self.programs, self.modules, self.subroutines, self.functions = [], [], [], []
        while self.stack:
            p, status = self.stack.pop(0)
            if status != "closed":
                print("WARNING: unclosed", repr(p), status, "ancestor", repr(p.ancestor))

            # Sort entries here.
            p.local_uses = sorted(p.local_uses)
            p.children = sorted(set(p.children))

            if p.ancestor is not None:
                #print("Adding %s to ancestor %s" % (repr(p), repr(p.ancestor)))
                p.ancestor.contains.append(p)
            else:
                if p.is_module: self.modules.append(p)
                elif p.is_program: self.programs.append(p)
                # Here only if sub/function outside module.
                elif p.is_subroutine: self.subroutines.append(p)
                elif p.is_function: self.functions.append(p)
                else: raise ValueError("Don't know how to handle type `%s`" % type(p))

        return self

    def warn(self, msg):
        cprint(msg, color="yellow")
        self.warnings.append(msg)

    def handle_contains(self, line):
        m = self.RE_CONTAINS.match(line)
        if not m: return False
        self.ancestor = self.stack[-1][0]
        if self.verbose > 1: print("Setting ancestor to:", repr(self.ancestor))
        return True

    def handle_cpp_line(self, line):
        # Handle include statement (CPP or Fortran version).
        if line.startswith("#include ") or line.startswith("include "):
            what = line.split()[1].replace("'", "").replace('"', "")
            if self.stack:
                self.stack[-1][0].includes.append(what)
            else:
                self.all_includes.append(what)
            return True
        return True if line[0] == "#" else False

    def handle_comment(self, line):
        # Count number of comments and code line
        # Inlined comments are not counted (also because I don't like them)
        if not line.startswith("!"):
            self.num_f90lines += 1
            return False

        # Count doc line and OMP (preamble in included in num_doclines
        if line.replace("!", ""): self.num_doclines += 1
        if line.startswith("!$omp"): self.num_omp_statements += 1

        if not self.stack or (self.stack and self.stack[-1][1] != "open"):
            # Ignore stupid robodoc marker.
            if line != "!!***":
                self.preamble.append(line)

        return True

    def handle_use_statement(self, line):
        # Find use statements and the corresponding module
        # TODO in principle one could have `use A; use B`
        if not line.startswith("use "): return False
        smod = line.split()[1].split(",")[0].lower()
        # Remove comment at the end of the line if present.
        i = smod.find("!")
        if i != -1: smod = smod[:i]
        if self.verbose > 1: print("Found used module:", smod)
        self.stack[-1][0].local_uses.append(smod)
        self.all_uses.append(smod)
        return True

    def handle_call(self, line):
        # At this level subname is a string that will be replaced by a Procedure object afterwards
        # TODO: should handle `call obj%foo()` syntax.
        m = self.RE_SUBCALL.match(line)
        if not m: return False
        subname = m.group("name")
        assert subname
        print("Adding %s to children of %s" % (subname, repr(self.stack[-1][0])))
        self.stack[-1][0].children.append(subname)
        return True

    def consume_module_header(self, line):
        m = self.RE_MOD_START.match(line)
        if not m: return False
        name = m.group("name")
        if self.verbose > 1: print("Entering module:", name)
        #assert self.ancestor is None
        module = Module(name, self.ancestor, self.preamble, path=self.path)
        self.ancestor = module
        self.stack.append([module, "open"])
        self.preamble = []

        while self.lines:
            line = self.lines.popleft()
            if not line: continue
            if self.handle_comment(line): continue
            line = line.lower()
            if self.handle_use_statement(line): continue
            m = self.RE_PUB_OR_PRIVATE.match(line)
            if m:
                module.default_visibility = m.group("name")
                continue

            # TODO: Procedure declaration statement.
            #proc_names
            #module.public_procedure_names.extend(proc_names)
            #module.private_procedure_names.extend(proc_names)

            # Interface declaration.
            if self.consume_interface(line): continue

            # Datatype declaration.
            if self.consume_datatype(line): continue

            # Exit here
            if self.handle_contains(line): return True
            # or here if the module does not have *contains*
            m = self.RE_MOD_END.match(line)
            if m:
                self.close_stack_entry(end_name=m.group("name"), end_proc_type="module")
                return True

        else:
            raise ValueError("Cannot find `contains` in %s" % self.path)

    def consume_interface(self, line):
        m = self.RE_INTERFACE_START.match(line)
        if not m: return False
        #assert self.stack[-1][1] == "open"
        buf = [line]
        name = m.group("name")
        if self.verbose > 1: print("begin interface", name, "in line:", line)
        while self.lines:
            line = self.lines.popleft()
            buf.append(line)
            end_match = self.RE_INTERFACE_END.match(line)
            if end_match:
                if self.verbose > 1: print("end interface", line)
                # Don't require `end interface name`
                #end_name = end_match.group("name")
                #if name != end_name: raise ValueError("`%s` != `%s`" % (name, end_name))
                self.stack[-1][0].interfaces.append(Interface(name, self.ancestor, buf))
                return True
        else:
            raise ValueError("Cannot find `end interface %s` in %s" % (name, self.path))

    def consume_datatype(self, line):
        m = self.RE_TYPE_START.match(line)
        if not m: return False
        buf = [line]
        name = m.group("name")
        if self.verbose > 1: print("begin datatype", name, "in line:", line)
        while self.lines:
            line = self.lines.popleft()
            buf.append(line)
            if self.handle_comment(line): continue
            line = line.lower()
            end_match = self.RE_TYPE_END.match(line)
            if end_match:
                end_name = end_match.group("name")
                if self.verbose > 1: print("end datatype %s in %s" % (end_name, line))
                if name == end_name:
                    self.stack[-1][0].types.append(Datatype(name, self.ancestor, buf))
                    return True
                else:
                    raise ValueError("Cannot find `end type %s` in %s" % (name, self.path))
        else:
            raise ValueError("Cannot find `end type %s` in %s" % (name, self.path))

    def handle_procedure(self, line):
        ptype = "subroutine"
        m = self.RE_SUB_START.match(line)
        re_end = self.RE_SUB_END
        if not m:
            m = self.RE_FUNC_START.match(line)
            re_end = self.RE_FUNC_END
            if m: ptype = "function"
        if not m:
            m = self.RE_PROG_START.match(line)
            re_end = self.RE_PROG_END
            if m: ptype = "program"

        if not m: return False

        # Extract name from (module | program).
        name = m.group("name")
        if not name:
            raise ValueError("Cannot find %s name in line `%s`" % (ptype, line))

        if self.verbose > 1:
            print("Found `%s %s`" % (ptype, name), "at line:\n\t", line)
            print("Ancestor is set to", repr(self.ancestor))

        if ptype == "subroutine":
            new_node = Subroutine(name, self.ancestor, self.preamble, path=self.path)
        elif ptype == "function":
            new_node = Function(name, self.ancestor, self.preamble, path=self.path)
        elif ptype == "program":
            new_node = Program(name, self.ancestor, self.preamble, path=self.path)
        else:
            raise ValueError(ptype)

        self.stack.append([new_node, "open"])
        self.ancestor = self.stack[-1][0]
        self.preamble = []
        self.num_f90lines, self.num_doclines, self.num_omp_statements = 0, 0, 0

        #"""
        has_contains = False
        while self.lines:
            line = self.lines.popleft()
            if not line: continue
            if self.handle_comment(line): continue
            line = line.lower()
            if self.handle_use_statement(line): continue
            if self.handle_cpp_line(line): continue
            if self.consume_interface(line): continue
            cont = self.handle_contains(line)
            if cont: has_contains = True
            if has_contains:
               if self.handle_procedure(line): continue

            m = self.RE_PROC_END.match(line)
            if m:
                #print(line)
                end_proc_type = m.group("proc_type")
                end_name = m.group("name")
                self.close_stack_entry(end_name, end_proc_type)
                break
        else:
            raise ValueError("Cannot find `end %s `%s`" % (ptype, name))
        #"""

        return True

    def close_stack_entry(self, end_name, end_proc_type):
        if end_name:
            # Close the last entry in the stack with name == end_name.
            for item in reversed(self.stack):
                if item[0].name == end_name:
                    node = item[0]
                    item[1] = "closed"
                    break
            else:
                raise RuntimeError("Cannot find end_name `%s` in stack:\n%s" % (
                    end_name, pformat([s[0].name for s in self.stack])))
        else:
            # Close the last entry in the stack with end_proc_type.
            if end_proc_type is not None:
                self.warn("Found `end %s` without name in %s" % (end_proc_type, self.path))
                for item in reversed(self.stack):
                    if item[0].proc_type == end_proc_type:
                        node = item[0]
                        item[1] = "closed"
                        break
                else:
                    raise RuntimeError("Cannot find end_proc_type `%s` in stack:\n%s" % (
                        end_proc_type, pformat([s[0].proc_type for s in self.stack])))
            else:
                # This is the best I can do.
                self.warn("Found plain `end` without procedure_type and name in %s" % (self.path))
                self.stack[-1][1] = "closed"
                node = stack[-1][0]

        if self.verbose > 1: print("Closing", repr(node))
        if self.ancestor is not None and self.ancestor.name == end_name:
            self.ancestor = self.ancestor.ancestor

        # Set attributes of last node.
        node.num_f90lines = self.num_f90lines
        node.num_doclines = self.num_doclines
        node.num_omp_statements = self.num_omp_statements

        #if self.preamble:
        #    self.warn("%s, preamble:\n%s" % (self.path, "\n".join(self.preamble)))
